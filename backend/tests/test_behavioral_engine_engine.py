"""Tests for Behavioral Engine — scoring, cold start, security, risk integration."""

from app.services.behavioral_engine.engine import BehavioralBaselineEngine
from app.services.behavioral_engine.models import (
    AnomalyContext,
    AnomalyDimension,
    BehavioralAnomalyResult,
    TransactionRecord,
)
from app.services.risk_engine.aggregator import compute_confidence
from app.services.risk_engine.constants import SIGNAL_WEIGHTS
from app.services.risk_engine.models import RiskContext, RiskSignalType, VelocityContext


def _make_ctx(
    transactions: list[dict],
    proposal_amount: float | None = None,
    proposal_merchant_id: str | None = None,
) -> AnomalyContext:
    records = [
        TransactionRecord(
            transaction_id=t.get("id", f"t{i}"),
            amount=t.get("amount", 100.0),
            currency=t.get("currency", "INR"),
            transaction_type=t.get("type", "purchase"),
            merchant_id=t.get("merchant_id"),
            created_at=t.get("created_at", "2025-01-15T10:00:00Z"),
        )
        for i, t in enumerate(transactions)
    ]
    return AnomalyContext(
        agent_id="agent-001",
        user_id="user-001",
        transactions=records,
        proposal_amount=proposal_amount,
        proposal_merchant_id=proposal_merchant_id,
        history_available=len(records) > 0,
    )


# ── Engine Basics ──────────────────────────────────────────────────


class TestEngineBasics:
    """Tests for basic engine behavior."""

    def test_empty_context(self):
        engine = BehavioralBaselineEngine()
        ctx = _make_ctx([])
        result = engine.evaluate(ctx)
        assert isinstance(result, BehavioralAnomalyResult)
        assert result.overall_score == 0.0
        # Frequency and merchant return UNKNOWN dimensions even with no data
        assert result.dimension_count >= 1

    def test_insufficient_history(self):
        """1 transaction → amount and frequency UNKNOWN, merchant may fire."""
        engine = BehavioralBaselineEngine()
        ctx = _make_ctx(
            [{"amount": 100.0, "created_at": "2025-01-15T10:00:00Z"}],
            proposal_amount=200.0,
        )
        result = engine.evaluate(ctx)
        # Amount needs 5 samples → 0 confidence
        # Frequency needs 3 samples → 0 confidence
        # Merchant can still evaluate with 1 transaction
        amount_dim = next(
            (d for d in result.dimensions if d.dimension == AnomalyDimension.AMOUNT),
            None,
        )
        assert amount_dim is not None
        assert amount_dim.confidence == 0.0
        assert amount_dim.score == 0.0

    def test_normal_transaction(self):
        """Transaction consistent with history → low anomaly."""
        engine = BehavioralBaselineEngine()
        # Use varying amounts so MAD is meaningful
        amounts = [
            80.0, 90.0, 100.0, 110.0, 120.0,
            95.0, 105.0, 85.0, 115.0, 100.0,
        ]
        txns = [
            {
                "amount": amounts[i],
                "merchant_id": "m1",
                "created_at": f"2025-01-{i + 1:02d}T10:00:00Z",
            }
            for i in range(10)
        ]
        ctx = _make_ctx(txns, proposal_amount=102.0, proposal_merchant_id="m1")
        result = engine.evaluate(ctx)
        # 102 is close to median (100), should be low anomaly
        assert result.overall_score <= 0.15
        assert result.confidence > 0.5

    def test_abnormal_amount(self):
        """Amount far from historical median → high anomaly."""
        engine = BehavioralBaselineEngine()
        txns = [
            {"amount": 500.0, "merchant_id": "m1", "created_at": f"2025-01-{i + 1:02d}T10:00:00Z"}
            for i in range(10)
        ]
        ctx = _make_ctx(txns, proposal_amount=50000.0, proposal_merchant_id="m1")
        result = engine.evaluate(ctx)
        assert result.overall_score > 0.30
        # Amount dimension should be the dominant signal
        amount_dim = next(
            (d for d in result.dimensions if d.dimension == AnomalyDimension.AMOUNT),
            None,
        )
        assert amount_dim is not None
        assert amount_dim.score > 0.30

    def test_new_merchant(self):
        """Merchant not in history → mild anomaly."""
        engine = BehavioralBaselineEngine()
        txns = [
            {"amount": 100.0, "merchant_id": "m1", "created_at": f"2025-01-{i + 1:02d}T10:00:00Z"}
            for i in range(10)
        ]
        ctx = _make_ctx(txns, proposal_amount=100.0, proposal_merchant_id="m999")
        result = engine.evaluate(ctx)
        merchant_dim = next(
            (d for d in result.dimensions if d.dimension == AnomalyDimension.MERCHANT),
            None,
        )
        assert merchant_dim is not None
        assert merchant_dim.score == 0.25  # New merchant

    def test_deterministic_evaluation(self):
        """Same input → same output."""
        engine = BehavioralBaselineEngine()
        txns = [
            {"amount": 100.0, "merchant_id": "m1", "created_at": f"2025-01-{i + 1:02d}T10:00:00Z"}
            for i in range(10)
        ]
        ctx = _make_ctx(txns, proposal_amount=120.0, proposal_merchant_id="m1")
        r1 = engine.evaluate(ctx)
        r2 = engine.evaluate(ctx)
        assert r1.overall_score == r2.overall_score
        assert r1.confidence == r2.confidence

    def test_result_has_metadata(self):
        engine = BehavioralBaselineEngine()
        ctx = _make_ctx([])
        result = engine.evaluate(ctx)
        assert result.evaluation_id != ""
        assert result.model_version == "behavioral-v1"
        assert result.evaluated_at != ""


# ── Cold Start ─────────────────────────────────────────────────────


class TestColdStart:
    """Tests for cold-start behavior."""

    def test_zero_transactions(self):
        engine = BehavioralBaselineEngine()
        ctx = _make_ctx([], proposal_amount=100.0)
        result = engine.evaluate(ctx)
        assert result.overall_score == 0.0
        # Dimensions still returned (frequency/merchant), but all 0 confidence
        assert result.confidence == 0.0

    def test_one_transaction(self):
        engine = BehavioralBaselineEngine()
        ctx = _make_ctx(
            [{"amount": 100.0, "created_at": "2025-01-15T10:00:00Z"}],
            proposal_amount=200.0,
        )
        result = engine.evaluate(ctx)
        # Amount needs 5 samples → 0 confidence
        amount_dim = next(
            (d for d in result.dimensions if d.dimension == AnomalyDimension.AMOUNT),
            None,
        )
        assert amount_dim is not None
        assert amount_dim.confidence == 0.0

    def test_five_transactions(self):
        """5 transactions → partial confidence for amount."""
        engine = BehavioralBaselineEngine()
        txns = [
            {"amount": 100.0, "created_at": f"2025-01-{i + 1:02d}T10:00:00Z"}
            for i in range(5)
        ]
        ctx = _make_ctx(txns, proposal_amount=110.0)
        result = engine.evaluate(ctx)
        amount_dim = next(
            (d for d in result.dimensions if d.dimension == AnomalyDimension.AMOUNT),
            None,
        )
        assert amount_dim is not None
        assert amount_dim.confidence > 0.0  # Partial confidence

    def test_twenty_transactions(self):
        """20 transactions → full confidence."""
        engine = BehavioralBaselineEngine()
        txns = [
            {
                "amount": 100.0,
                "merchant_id": "m1",
                "created_at": (
                    f"2025-01-{(i % 28) + 1:02d}"
                    f"T{(i // 28) + 10:02d}:00:00Z"
                ),
            }
            for i in range(20)
        ]
        ctx = _make_ctx(txns, proposal_amount=105.0, proposal_merchant_id="m1")
        result = engine.evaluate(ctx)
        assert result.confidence > 0.8


# ── Data Leakage ───────────────────────────────────────────────────


class TestDataLeakage:
    """Verify current transaction doesn't influence baseline."""

    def test_changing_current_does_not_alter_baseline(self):
        """Changing proposal_amount should not change baseline statistics."""
        engine = BehavioralBaselineEngine()
        txns = [
            {"amount": 100.0, "created_at": f"2025-01-{i + 1:02d}T10:00:00Z"}
            for i in range(10)
        ]
        ctx1 = _make_ctx(txns, proposal_amount=110.0)
        ctx2 = _make_ctx(txns, proposal_amount=50000.0)

        r1 = engine.evaluate(ctx1)
        r2 = engine.evaluate(ctx2)

        # Baseline should be identical — only the anomaly score changes
        d1 = next(d for d in r1.dimensions if d.dimension == AnomalyDimension.AMOUNT)
        d2 = next(d for d in r2.dimensions if d.dimension == AnomalyDimension.AMOUNT)
        assert d1.evidence["median"] == d2.evidence["median"]
        assert d1.evidence["mad"] == d2.evidence["mad"]
        assert d1.score != d2.score  # But anomaly scores differ


# ── Risk Engine Integration ────────────────────────────────────────


class TestRiskEngineIntegration:
    """Tests for behavioral anomaly integration with Risk Engine."""

    def _make_risk_ctx(
        self,
        behavioral_available: bool = False,
        amount_score: float | None = None,
        freq_score: float | None = None,
        merchant_score: float | None = None,
    ) -> RiskContext:
        return RiskContext(
            user_id="u1",
            agent_id="a1",
            intent_id="i1",
            intent_version=1,
            drift_available=True,
            drift_overall_status="match",
            drift_severity="none",
            policy_available=True,
            agent_trust_score=0.8,
            merchant_trust_score=0.7,
            velocity=VelocityContext(history_available=True),
            behavioral_anomaly_available=behavioral_available,
            behavioral_anomaly_amount_score=amount_score,
            behavioral_anomaly_frequency_score=freq_score,
            behavioral_anomaly_merchant_score=merchant_score,
        )

    def test_no_behavioral_no_change(self):
        ctx_without = self._make_risk_ctx(behavioral_available=False)
        ctx_with_zero = self._make_risk_ctx(
            behavioral_available=True, amount_score=0.0
        )
        signals = []
        c1 = compute_confidence(ctx_without, signals)
        c2 = compute_confidence(ctx_with_zero, signals)
        assert c1 == c2

    def test_high_amount_anomaly_reduces_confidence(self):
        ctx_clean = self._make_risk_ctx(behavioral_available=True)
        ctx_anomaly = self._make_risk_ctx(
            behavioral_available=True, amount_score=0.50
        )
        signals = []
        c_clean = compute_confidence(ctx_clean, signals)
        c_anomaly = compute_confidence(ctx_anomaly, signals)
        assert c_anomaly < c_clean

    def test_all_anomalies_combined(self):
        ctx_clean = self._make_risk_ctx(behavioral_available=True)
        ctx_all = self._make_risk_ctx(
            behavioral_available=True,
            amount_score=0.50,
            freq_score=0.30,
            merchant_score=0.25,
        )
        signals = []
        c_clean = compute_confidence(ctx_clean, signals)
        c_all = compute_confidence(ctx_all, signals)
        assert c_all < c_clean
        assert c_all >= 0.1  # Floor

    def test_low_anomaly_no_reduction(self):
        ctx = self._make_risk_ctx(
            behavioral_available=True,
            amount_score=0.05,
            freq_score=0.08,
            merchant_score=0.10,
        )
        signals = []
        c = compute_confidence(ctx, signals)
        ctx_clean = self._make_risk_ctx(behavioral_available=True)
        c_clean = compute_confidence(ctx_clean, signals)
        assert c == c_clean


# ── Weight Invariant ───────────────────────────────────────────────


class TestWeightInvariant:
    """Verify Sprint 7/8/9 weights are preserved."""

    def test_original_sprint7_weights_preserved(self):
        expected = {
            RiskSignalType.INTENT_DRIFT: 0.25,
            RiskSignalType.AMOUNT_ANOMALY: 0.15,
            RiskSignalType.AGENT_TRUST: 0.15,
            RiskSignalType.MERCHANT_TRUST: 0.10,
            RiskSignalType.POLICY_INTERACTION: 0.20,
            RiskSignalType.VELOCITY: 0.05,
            RiskSignalType.DATA_QUALITY: 0.00,
            RiskSignalType.CURRENCY_MISMATCH: 0.05,
            RiskSignalType.GEOGRAPHIC_ANOMALY: 0.05,
        }
        for key, value in expected.items():
            assert SIGNAL_WEIGHTS[key] == value, f"Weight for {key} changed"

    def test_nonzero_weights_sum_to_one(self):
        nonzero = {k: v for k, v in SIGNAL_WEIGHTS.items() if v > 0}
        total = sum(nonzero.values())
        assert abs(total - 1.0) < 1e-9


# ── Security ───────────────────────────────────────────────────────


class TestSecurity:
    """Verify no dangerous patterns exist."""

    def test_no_eval_exec(self):
        import os
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "behavioral_engine"
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read()
                assert "eval(" not in content, f"eval() found in {filename}"
                assert "exec(" not in content, f"exec() found in {filename}"

    def test_no_dynamic_imports(self):
        import os
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "behavioral_engine"
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read()
                assert "__import__" not in content, f"__import__ found in {filename}"
                assert "importlib" not in content, f"importlib found in {filename}"

    def test_no_llm_imports(self):
        import os
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "behavioral_engine"
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read().lower()
                assert "openai" not in content, f"openai found in {filename}"
                assert "gemini" not in content, f"gemini found in {filename}"

    def test_no_subprocess(self):
        import os
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "behavioral_engine"
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read()
                assert "subprocess" not in content, f"subprocess found in {filename}"

    def test_no_sqlalchemy_in_core(self):
        """Core behavioral engine should not import SQLAlchemy."""
        import os
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "behavioral_engine"
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read().lower()
                assert "sqlalchemy" not in content, f"sqlalchemy found in {filename}"

"""Tests for Graph Risk Engine integration — engine, Risk Engine, backward compatibility."""


from app.services.graph_risk_engine.engine import GraphRiskEngine
from app.services.graph_risk_engine.models import (
    AgentTransactionRecord,
    GraphContext,
    NetworkRiskResult,
    NetworkSignalType,
    SiblingAgentRecord,
)
from app.services.risk_engine.aggregator import compute_confidence
from app.services.risk_engine.constants import SIGNAL_WEIGHTS
from app.services.risk_engine.models import RiskContext, RiskSignalType, VelocityContext

# ── GRAPH RISK ENGINE ──────────────────────────────────────────────


class TestGraphRiskEngine:
    """Tests for the GraphRiskEngine orchestrator."""

    def test_empty_context(self):
        """Empty context → empty result with 0 score."""
        engine = GraphRiskEngine()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
        )
        result = engine.evaluate(ctx)
        assert isinstance(result, NetworkRiskResult)
        assert result.overall_score == 0.0
        assert result.signal_count == 0

    def test_unavailable_context(self):
        """Unavailable graph → empty result."""
        engine = GraphRiskEngine()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            graph_available=False,
        )
        result = engine.evaluate(ctx)
        assert result.overall_score == 0.0
        assert result.signal_count == 0

    def test_risk_signals_produced(self):
        """With sufficient data, signals are produced."""
        engine = GraphRiskEngine()
        txns = [
            AgentTransactionRecord(
                transaction_id=f"t{i}",
                merchant_id="m1" if i < 7 else f"m{i}",
                amount=100.0,
                created_at=f"2025-01-{i + 1:02d}T10:00:00Z",
            )
            for i in range(10)
        ]
        siblings = [
            SiblingAgentRecord(agent_id="a2", trust_score=0.1, status="active"),
            SiblingAgentRecord(agent_id="a3", trust_score=0.8, status="active"),
        ]
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=txns,
            sibling_agents=siblings,
        )
        result = engine.evaluate(ctx)
        assert result.signal_count >= 1  # At least concentration
        assert 0.0 <= result.overall_score <= 1.0

    def test_deterministic_evaluation(self):
        """Same context → same result."""
        engine = GraphRiskEngine()
        txns = [
            AgentTransactionRecord(
                transaction_id=f"t{i}",
                merchant_id="m1",
                amount=100.0,
                created_at=f"2025-01-{i + 1:02d}T10:00:00Z",
            )
            for i in range(5)
        ]
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=txns,
        )
        r1 = engine.evaluate(ctx)
        r2 = engine.evaluate(ctx)
        assert r1.overall_score == r2.overall_score
        assert r1.confidence == r2.confidence
        assert r1.signal_count == r2.signal_count

    def test_result_has_metadata(self):
        """Result includes evaluation metadata."""
        engine = GraphRiskEngine()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
        )
        result = engine.evaluate(ctx)
        assert result.evaluation_id != ""
        assert result.model_version == "graph-risk-v1"
        assert result.evaluated_at != ""

    def test_result_has_statistics(self):
        """Result includes graph statistics."""
        engine = GraphRiskEngine()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0,
                    created_at="2025-01-15T10:00:00Z",
                ),
            ],
        )
        result = engine.evaluate(ctx)
        assert result.graph_statistics.total_agent_transactions == 1
        assert result.graph_statistics.unique_merchants == 1

    def test_summary_generated(self):
        """Result has a non-empty summary."""
        engine = GraphRiskEngine()
        txns = [
            AgentTransactionRecord(
                transaction_id=f"t{i}",
                merchant_id="m1" if i < 8 else f"m{i}",
                amount=100.0,
                created_at=f"2025-01-{i + 1:02d}T10:00:00Z",
            )
            for i in range(10)
        ]
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=txns,
        )
        result = engine.evaluate(ctx)
        assert result.summary != ""


# ── RISK ENGINE INTEGRATION ────────────────────────────────────────


class TestRiskEngineIntegration:
    """Tests for graph risk integration into Risk Engine confidence."""

    def _make_risk_context(
        self,
        network_risk_available: bool = False,
        network_risk_score: float | None = None,
        shared_exposure: float | None = None,
        concentration: float | None = None,
        cluster_risk: float | None = None,
    ) -> RiskContext:
        return RiskContext(
            user_id="user-001",
            agent_id="agent-001",
            intent_id="intent-001",
            intent_version=1,
            drift_available=True,
            drift_overall_status="match",
            drift_severity="none",
            policy_available=True,
            agent_trust_score=0.8,
            merchant_trust_score=0.7,
            velocity=VelocityContext(history_available=True),
            network_risk_available=network_risk_available,
            network_risk_score=network_risk_score,
            network_risk_shared_exposure_score=shared_exposure,
            network_risk_concentration_score=concentration,
            network_risk_cluster_risk_score=cluster_risk,
        )

    def test_no_network_risk_no_change(self):
        """When network risk is unavailable, confidence is unchanged."""
        ctx_without = self._make_risk_context(network_risk_available=False)
        ctx_with_zero = self._make_risk_context(
            network_risk_available=True,
            network_risk_score=0.0,
        )
        signals = []
        c1 = compute_confidence(ctx_without, signals)
        c2 = compute_confidence(ctx_with_zero, signals)
        # Zero network risk should not reduce confidence
        assert c1 == c2

    def test_high_shared_risk_reduces_confidence(self):
        """High shared risk exposure → confidence reduced."""
        ctx_clean = self._make_risk_context(network_risk_available=True)
        ctx_risky = self._make_risk_context(
            network_risk_available=True,
            shared_exposure=0.50,
        )
        signals = []
        c_clean = compute_confidence(ctx_clean, signals)
        c_risky = compute_confidence(ctx_risky, signals)
        assert c_risky < c_clean

    def test_high_concentration_reduces_confidence(self):
        """High merchant concentration → confidence reduced."""
        ctx_clean = self._make_risk_context(network_risk_available=True)
        ctx_concentrated = self._make_risk_context(
            network_risk_available=True,
            concentration=0.40,
        )
        signals = []
        c_clean = compute_confidence(ctx_clean, signals)
        c_conc = compute_confidence(ctx_concentrated, signals)
        assert c_conc < c_clean

    def test_cluster_risk_reduces_confidence(self):
        """Agent cluster risk → confidence reduced."""
        ctx_clean = self._make_risk_context(network_risk_available=True)
        ctx_cluster = self._make_risk_context(
            network_risk_available=True,
            cluster_risk=0.30,
        )
        signals = []
        c_clean = compute_confidence(ctx_clean, signals)
        c_cluster = compute_confidence(ctx_cluster, signals)
        assert c_cluster < c_clean

    def test_all_network_risks_combined(self):
        """All three network risks → maximum confidence reduction."""
        ctx_clean = self._make_risk_context(network_risk_available=True)
        ctx_all = self._make_risk_context(
            network_risk_available=True,
            shared_exposure=0.50,
            concentration=0.40,
            cluster_risk=0.30,
        )
        signals = []
        c_clean = compute_confidence(ctx_clean, signals)
        c_all = compute_confidence(ctx_all, signals)
        assert c_all < c_clean
        # Confidence should not drop below floor
        assert c_all >= 0.1

    def test_low_network_risk_no_reduction(self):
        """Network risk scores below threshold (<=0.10) → no reduction."""
        ctx = self._make_risk_context(
            network_risk_available=True,
            shared_exposure=0.05,
            concentration=0.08,
            cluster_risk=0.10,
        )
        signals = []
        c = compute_confidence(ctx, signals)
        ctx_clean = self._make_risk_context(network_risk_available=True)
        c_clean = compute_confidence(ctx_clean, signals)
        assert c == c_clean


# ── WEIGHT INVARIANT ───────────────────────────────────────────────


class TestWeightInvariant:
    """Verify Sprint 7/8 weights are preserved exactly."""

    def test_original_sprint7_weights_preserved(self):
        """All 9 Sprint 7 weights remain exactly as calibrated."""
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
        """Sum of non-zero weights must equal 1.0."""
        nonzero = {k: v for k, v in SIGNAL_WEIGHTS.items() if v > 0}
        total = sum(nonzero.values())
        assert abs(total - 1.0) < 1e-9

    def test_network_risk_not_in_signal_weights(self):
        """NETWORK_RISK is not a weighted signal — it uses confidence path."""
        # Ensure no NetworkSignalType exists in SIGNAL_WEIGHTS
        for key in SIGNAL_WEIGHTS:
            assert key not in (
                NetworkSignalType.SHARED_RISK_EXPOSURE,
                NetworkSignalType.MERCHANT_CONCENTRATION,
                NetworkSignalType.AGENT_CLUSTER_RISK,
            ), f"Network signal type {key} should not be in SIGNAL_WEIGHTS"


# ── AGENT_TRUST/AGENT_BEHAVIOR MUTUAL EXCLUSION ────────────────────


class TestMutualExclusionPreserved:
    """Verify Sprint 8 trust signal mutual exclusion is unchanged."""

    def test_agent_trust_and_behavior_not_both_present(self):
        """AGENT_TRUST and AGENT_BEHAVIOR cannot both have weight > 0."""
        trust_weight = SIGNAL_WEIGHTS.get(RiskSignalType.AGENT_TRUST, 0)
        behavior_weight = SIGNAL_WEIGHTS.get(RiskSignalType.AGENT_BEHAVIOR, 0)
        # Only one should have the actual 0.15 weight
        # AGENT_BEHAVIOR is not in SIGNAL_WEIGHTS (uses AGENT_TRUST's weight)
        assert trust_weight == 0.15
        assert behavior_weight == 0.0 or RiskSignalType.AGENT_BEHAVIOR not in SIGNAL_WEIGHTS


# ── SECURITY ───────────────────────────────────────────────────────


class TestSecurity:
    """Verify no dangerous patterns exist in the graph risk engine."""

    def test_no_eval_exec(self):
        """No eval() or exec() in graph risk engine files."""
        import os
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "graph_risk_engine"
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read()
                assert "eval(" not in content, f"eval() found in {filename}"
                assert "exec(" not in content, f"exec() found in {filename}"

    def test_no_dynamic_imports(self):
        """No __import__ or importlib in graph risk engine files."""
        import os
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "graph_risk_engine"
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read()
                assert "__import__" not in content, f"__import__ found in {filename}"
                assert "importlib" not in content, f"importlib found in {filename}"

    def test_no_llm_imports(self):
        """No LLM/OpenAI/Gemini imports in graph risk engine."""
        import os
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "graph_risk_engine"
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read().lower()
                assert "openai" not in content, f"openai found in {filename}"
                assert "gemini" not in content, f"gemini found in {filename}"
                assert "anthropic" not in content, f"anthropic found in {filename}"

    def test_no_payment_references(self):
        """No Razorpay or payment execution in graph risk engine."""
        import os
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "graph_risk_engine"
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read().lower()
                assert "razorpay" not in content, f"razorpay found in {filename}"

    def test_no_subprocess(self):
        """No subprocess calls in graph risk engine."""
        import os
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "graph_risk_engine"
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read()
                assert "subprocess" not in content, f"subprocess found in {filename}"


# ── BACKWARD COMPATIBILITY ─────────────────────────────────────────


class TestBackwardCompatibility:
    """Verify graph risk doesn't change existing Risk Engine behavior."""

    def test_risk_context_defaults_preserve_sprint8(self):
        """Default RiskContext (no network risk) matches Sprint 8 behavior."""
        ctx = RiskContext(
            user_id="u1",
            agent_id="a1",
            intent_id="i1",
            intent_version=1,
        )
        # Network risk fields default to unavailable/None
        assert ctx.network_risk_available is False
        assert ctx.network_risk_score is None

    def test_network_risk_score_bounds(self):
        """Network risk score fields respect bounds."""
        ctx = RiskContext(
            user_id="u1",
            agent_id="a1",
            intent_id="i1",
            intent_version=1,
            network_risk_available=True,
            network_risk_score=0.5,
            network_risk_confidence=0.8,
            network_risk_shared_exposure_score=0.3,
            network_risk_concentration_score=0.2,
            network_risk_cluster_risk_score=0.1,
        )
        assert 0.0 <= ctx.network_risk_score <= 1.0
        assert 0.0 <= ctx.network_risk_confidence <= 1.0

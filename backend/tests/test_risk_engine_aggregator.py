"""Tests for Risk Engine aggregator, engine, and integration.

All tests are deterministic, offline, and database-independent.
"""

from decimal import Decimal

from app.services.risk_engine.aggregator import (
    apply_correlation_groups,
    apply_dominant_boost,
    compute_confidence,
    compute_weighted_score,
    score_to_level,
)
from app.services.risk_engine.constants import SIGNAL_WEIGHTS
from app.services.risk_engine.engine import RiskEngine
from app.services.risk_engine.models import (
    RiskContext,
    RiskEvidence,
    RiskLevel,
    RiskSignalType,
    SourceEngine,
    VelocityContext,
)


def _make_ctx(**overrides) -> RiskContext:
    defaults = {
        "user_id": "u1",
        "agent_id": "a1",
        "intent_id": "i1",
        "intent_version": 1,
    }
    defaults.update(overrides)
    return RiskContext(**defaults)


def _make_signal(
    signal_type: RiskSignalType,
    contribution: float,
    confidence: float = 1.0,
) -> RiskEvidence:
    return RiskEvidence(
        signal_type=signal_type,
        risk_contribution=contribution,
        confidence=confidence,
        what="test",
        why="test",
        source_engine=SourceEngine.RISK_ENGINE,
    )


# ── Correlation ────────────────────────────────────────────────────


class TestCorrelationGroups:
    def test_drift_amount_discount(self):
        signals = [
            _make_signal(RiskSignalType.INTENT_DRIFT, 0.45),
            _make_signal(RiskSignalType.AMOUNT_ANOMALY, 0.30),
        ]
        result = apply_correlation_groups(signals)
        # Sorted alphabetically: AMOUNT_ANOMALY first (full), INTENT_DRIFT second (discounted)
        drift_sig = next(s for s in result if s.signal_type == RiskSignalType.INTENT_DRIFT)
        amount_sig = next(s for s in result if s.signal_type == RiskSignalType.AMOUNT_ANOMALY)
        assert amount_sig.risk_contribution == 0.30  # First in alpha sort = full
        assert drift_sig.risk_contribution == 0.45 * 0.6  # Second = discounted

    def test_trust_discount(self):
        signals = [
            _make_signal(RiskSignalType.AGENT_TRUST, 0.30),
            _make_signal(RiskSignalType.MERCHANT_TRUST, 0.25),
        ]
        result = apply_correlation_groups(signals)
        agent_sig = next(s for s in result if s.signal_type == RiskSignalType.AGENT_TRUST)
        merchant_sig = next(s for s in result if s.signal_type == RiskSignalType.MERCHANT_TRUST)
        assert agent_sig.risk_contribution == 0.30
        assert merchant_sig.risk_contribution == 0.25 * 0.7

    def test_geographic_discount(self):
        signals = [
            _make_signal(RiskSignalType.GEOGRAPHIC_ANOMALY, 0.10),
            _make_signal(RiskSignalType.CURRENCY_MISMATCH, 0.15),
        ]
        result = apply_correlation_groups(signals)
        geo_sig = next(s for s in result if s.signal_type == RiskSignalType.GEOGRAPHIC_ANOMALY)
        cur_sig = next(s for s in result if s.signal_type == RiskSignalType.CURRENCY_MISMATCH)
        # Alphabetically: CURRENCY_MISMATCH first (full), GEOGRAPHIC_ANOMALY second (discounted)
        assert cur_sig.risk_contribution == 0.15  # First in alpha sort = full
        assert geo_sig.risk_contribution == 0.10 * 0.5  # Second = discounted

    def test_independent_groups_no_discount(self):
        signals = [
            _make_signal(RiskSignalType.INTENT_DRIFT, 0.45),
            _make_signal(RiskSignalType.AGENT_TRUST, 0.30),
        ]
        result = apply_correlation_groups(signals)
        for s in result:
            if s.signal_type == RiskSignalType.INTENT_DRIFT:
                assert s.risk_contribution == 0.45
            elif s.signal_type == RiskSignalType.AGENT_TRUST:
                assert s.risk_contribution == 0.30

    def test_deterministic_ordering(self):
        signals = [
            _make_signal(RiskSignalType.AMOUNT_ANOMALY, 0.30),
            _make_signal(RiskSignalType.INTENT_DRIFT, 0.45),
        ]
        result1 = apply_correlation_groups(signals)
        result2 = apply_correlation_groups(list(reversed(signals)))
        c1 = [s.risk_contribution for s in result1]
        c2 = [s.risk_contribution for s in result2]
        assert sorted(c1) == sorted(c2)


# ── Weighted Score ─────────────────────────────────────────────────


class TestWeightedScore:
    def test_single_signal(self):
        signals = [_make_signal(RiskSignalType.INTENT_DRIFT, 0.50)]
        score = compute_weighted_score(signals)
        assert score == 0.50

    def test_multiple_signals(self):
        signals = [
            _make_signal(RiskSignalType.INTENT_DRIFT, 0.45),
            _make_signal(RiskSignalType.AGENT_TRUST, 0.30),
        ]
        score = compute_weighted_score(signals)
        expected = (0.45 * 0.25 + 0.30 * 0.15) / (0.25 + 0.15)
        assert abs(score - expected) < 0.001

    def test_empty_signals(self):
        assert compute_weighted_score([]) == 0.0

    def test_data_quality_excluded(self):
        signals = [_make_signal(RiskSignalType.DATA_QUALITY, 0.50)]
        score = compute_weighted_score(signals)
        assert score == 0.0  # DATA_QUALITY weight is 0

    def test_weight_redistribution(self):
        signals = [
            _make_signal(RiskSignalType.INTENT_DRIFT, 0.50),
            _make_signal(RiskSignalType.AMOUNT_ANOMALY, 0.30),
        ]
        score = compute_weighted_score(signals)
        w_drift = SIGNAL_WEIGHTS[RiskSignalType.INTENT_DRIFT]
        w_amount = SIGNAL_WEIGHTS[RiskSignalType.AMOUNT_ANOMALY]
        total_weight = w_drift + w_amount
        expected = (0.50 * w_drift + 0.30 * w_amount) / total_weight
        assert abs(score - expected) < 0.001


# ── Dominant Signal ────────────────────────────────────────────────


class TestDominantBoost:
    def test_no_dominant_signal(self):
        signals = [_make_signal(RiskSignalType.AGENT_TRUST, 0.30)]
        score = compute_weighted_score(signals)
        result = apply_dominant_boost(score, signals)
        assert result == score

    def test_dominant_signal_boosts(self):
        signals = [_make_signal(RiskSignalType.INTENT_DRIFT, 0.65)]
        score = compute_weighted_score(signals)
        result = apply_dominant_boost(score, signals)
        assert result >= score

    def test_boost_caps_at_100(self):
        signals = [_make_signal(RiskSignalType.INTENT_DRIFT, 0.90)]
        score = compute_weighted_score(signals)
        result = apply_dominant_boost(score, signals)
        assert result <= 1.0


# ── Confidence ─────────────────────────────────────────────────────


class TestConfidence:
    def test_full_data_high_confidence(self):
        ctx = _make_ctx(
            drift_available=True,
            agent_trust_score=0.8,
            proposal_merchant_trusted=True,
            velocity=VelocityContext(history_available=True),
            intent_confidence=0.9,
            policy_available=True,
            proposal_amount=Decimal("5000"),
        )
        signals = [_make_signal(RiskSignalType.INTENT_DRIFT, 0.10)]
        conf = compute_confidence(ctx, signals)
        assert conf >= 0.9

    def test_missing_drift_reduces(self):
        ctx = _make_ctx(
            drift_available=False,
            agent_trust_score=0.8,
            proposal_merchant_trusted=True,
            velocity=VelocityContext(history_available=True),
            intent_confidence=0.9,
            policy_available=True,
        )
        signals = []
        conf = compute_confidence(ctx, signals)
        assert conf < 1.0

    def test_all_missing_minimum(self):
        ctx = _make_ctx(
            drift_available=False,
            agent_trust_score=None,
            proposal_merchant_trusted=None,
            merchant_trust_score=None,
            velocity=None,
            intent_confidence=None,
            policy_available=False,
            proposal_amount=None,
        )
        signals = []
        conf = compute_confidence(ctx, signals)
        assert conf >= 0.1  # Floor

    def test_confidence_never_below_floor(self):
        ctx = _make_ctx(
            drift_available=False,
            agent_trust_score=None,
            proposal_merchant_trusted=None,
            merchant_trust_score=None,
            velocity=None,
            intent_confidence=None,
            policy_available=False,
            proposal_amount=None,
        )
        signals = [_make_signal(RiskSignalType.DATA_QUALITY, 0.0, confidence=0.1)]
        conf = compute_confidence(ctx, signals)
        assert conf >= 0.1

    def test_signal_confidence_blends(self):
        ctx = _make_ctx(
            drift_available=True,
            agent_trust_score=0.8,
            proposal_merchant_trusted=True,
            velocity=VelocityContext(history_available=True),
            intent_confidence=0.9,
            policy_available=True,
            proposal_amount=Decimal("5000"),
        )
        signals = [_make_signal(RiskSignalType.INTENT_DRIFT, 0.10, confidence=0.5)]
        conf = compute_confidence(ctx, signals)
        # Should be between full context confidence and signal confidence
        assert 0.5 < conf < 1.0


# ── Risk Level Mapping ─────────────────────────────────────────────


class TestRiskLevelMapping:
    def test_low_boundary(self):
        assert score_to_level(0.0) == RiskLevel.LOW
        assert score_to_level(0.24) == RiskLevel.LOW

    def test_medium_boundary(self):
        assert score_to_level(0.25) == RiskLevel.MEDIUM
        assert score_to_level(0.49) == RiskLevel.MEDIUM

    def test_high_boundary(self):
        assert score_to_level(0.50) == RiskLevel.HIGH
        assert score_to_level(0.74) == RiskLevel.HIGH

    def test_critical_boundary(self):
        assert score_to_level(0.75) == RiskLevel.CRITICAL
        assert score_to_level(1.0) == RiskLevel.CRITICAL


# ── RiskEngine Core ────────────────────────────────────────────────


class TestRiskEngine:
    def test_minimal_context(self):
        engine = RiskEngine()
        ctx = _make_ctx()
        result = engine.evaluate(ctx)
        assert result.risk_level == RiskLevel.LOW
        assert result.confidence >= 0.1

    def test_full_positive_context(self):
        engine = RiskEngine()
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="match",
            drift_severity="none",
            agent_trust_score=0.9,
            proposal_merchant_trusted=True,
            velocity=VelocityContext(history_available=True),
            intent_confidence=0.95,
            policy_available=True,
            proposal_amount=Decimal("3000"),
            intent_amount_max=5000.0,
        )
        result = engine.evaluate(ctx)
        assert result.overall_score < 0.25
        assert result.risk_level == RiskLevel.LOW

    def test_high_risk_context(self):
        engine = RiskEngine()
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="critical",
            agent_trust_score=0.1,
            proposal_merchant_trusted=False,
            velocity=VelocityContext(
                transactions_last_hour=10,
                total_amount_last_hour=Decimal("20000"),
                same_merchant_count_last_hour=5,
                history_available=True,
            ),
            intent_confidence=0.3,
            policy_available=True,
            policy_triggered_count=4,
            policy_highest_severity="critical",
            proposal_amount=Decimal("20000"),
            intent_amount_max=5000.0,
            intent_currency="INR",
            proposal_currency="USD",
            intent_country="IN",
            proposal_country="US",
        )
        result = engine.evaluate(ctx)
        # Multiple strong signals → MEDIUM or HIGH
        assert result.overall_score >= 0.35
        assert result.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)
        # Verify signals are present
        assert result.signal_count >= 5

    def test_signals_sorted_by_contribution(self):
        engine = RiskEngine()
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="high",
            agent_trust_score=0.3,
            proposal_merchant_trusted=True,
            velocity=VelocityContext(history_available=True),
            intent_confidence=0.8,
            policy_available=True,
            proposal_amount=Decimal("8000"),
            intent_amount_max=5000.0,
        )
        result = engine.evaluate(ctx)
        if len(result.signals) > 1:
            for i in range(len(result.signals) - 1):
                curr = result.signals[i].risk_contribution
                nxt = result.signals[i + 1].risk_contribution
                assert curr >= nxt

    def test_result_has_metadata(self):
        engine = RiskEngine()
        ctx = _make_ctx()
        result = engine.evaluate(ctx)
        assert result.evaluation_id != ""
        assert result.risk_model_version == "deterministic-v1"
        assert result.evaluator_version == "risk-v1"
        assert result.evaluated_at != ""

    def test_result_has_summary(self):
        engine = RiskEngine()
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="high",
            agent_trust_score=0.3,
        )
        result = engine.evaluate(ctx)
        assert result.summary != ""

    def test_deterministic_same_input_same_output(self):
        engine = RiskEngine()
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="match",
            agent_trust_score=0.8,
        )
        r1 = engine.evaluate(ctx)
        r2 = engine.evaluate(ctx)
        assert r1.overall_score == r2.overall_score
        assert r1.risk_level == r2.risk_level
        assert r1.confidence == r2.confidence

    def test_score_clamped(self):
        engine = RiskEngine()
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="critical",
            drift_amount_deviation_percent=Decimal("200"),
            agent_trust_score=0.01,
            proposal_merchant_trusted=False,
            velocity=VelocityContext(
                transactions_last_hour=10,
                total_amount_last_hour=Decimal("100000"),
                history_available=True,
            ),
            intent_amount_max=5000.0,
            policy_available=True,
            policy_triggered_count=5,
            policy_highest_severity="critical",
            proposal_amount=Decimal("50000"),
            intent_confidence=0.1,
        )
        result = engine.evaluate(ctx)
        assert 0.0 <= result.overall_score <= 1.0

    def test_component_scores_populated(self):
        engine = RiskEngine()
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="high",
            agent_trust_score=0.4,
            proposal_merchant_trusted=True,
            velocity=VelocityContext(history_available=True),
            intent_confidence=0.8,
            policy_available=True,
            proposal_amount=Decimal("8000"),
            intent_amount_max=5000.0,
        )
        result = engine.evaluate(ctx)
        assert result.component_scores is not None
        # At least some component scores should be populated
        scores = result.component_scores.model_dump()
        populated = [v for v in scores.values() if v is not None]
        assert len(populated) > 0


# ── Security Tests ─────────────────────────────────────────────────


class TestSecurity:
    def test_no_eval_in_engine(self):
        import inspect

        from app.services.risk_engine import engine
        source = inspect.getsource(engine)
        assert "eval(" not in source

    def test_no_exec_in_engine(self):
        import inspect

        from app.services.risk_engine import engine
        source = inspect.getsource(engine)
        assert "exec(" not in source

    def test_no_subprocess_in_engine(self):
        import inspect

        from app.services.risk_engine import engine
        source = inspect.getsource(engine)
        assert "subprocess" not in source

    def test_no_llm_in_engine(self):
        import inspect

        from app.services.risk_engine import engine
        source = inspect.getsource(engine)
        assert "gemini" not in source.lower()
        assert "openai" not in source.lower()

    def test_no_payment_in_engine(self):
        import inspect

        from app.services.risk_engine import engine
        source = inspect.getsource(engine)
        code_only = "\n".join(
            line for line in source.split("\n")
            if not line.strip().startswith("#")
            and not line.strip().startswith('"""')
        )
        assert "razorpay" not in code_only.lower()
        assert "process_payment" not in code_only.lower()

    def test_no_database_in_risk_engine(self):
        import inspect

        from app.services.risk_engine import engine
        source = inspect.getsource(engine)
        assert "AsyncSession" not in source
        assert "select(" not in source

    def test_no_allow_block_in_risk_engine(self):
        import inspect

        from app.services.risk_engine import engine
        source = inspect.getsource(engine)
        code_only = "\n".join(
            line for line in source.split("\n")
            if not line.strip().startswith("#")
            and not line.strip().startswith('"""')
        )
        assert '"allow"' not in code_only
        assert '"block"' not in code_only
        assert '"review"' not in code_only

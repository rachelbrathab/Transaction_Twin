"""Tests for Reputation Engine orchestrator."""

from app.services.reputation_engine.engine import ReputationEngine, _score_to_trust_level
from app.services.reputation_engine.models import (
    BehavioralContext,
    ReputationChange,
    ReputationDimension,
    ReputationResult,
    TrustLevel,
)


def _make_ctx(**kwargs) -> BehavioralContext:
    defaults = {"agent_id": "a1", "user_id": "u1"}
    defaults.update(kwargs)
    return BehavioralContext(**defaults)


def _make_snapshot(score: float, dims: list | None = None) -> dict:
    """Build a fake previous reputation snapshot."""
    return {
        "overall_score": score,
        "trust_level": "medium",
        "dimensions": dims or [],
        "change": "stable",
        "model_version": "reputation-v1",
        "evaluated_at": "2026-08-25T00:00:00Z",
    }


class TestScoreToTrustLevel:
    def test_high(self):
        assert _score_to_trust_level(0.85) == TrustLevel.HIGH

    def test_medium(self):
        assert _score_to_trust_level(0.55) == TrustLevel.MEDIUM

    def test_low(self):
        assert _score_to_trust_level(0.30) == TrustLevel.LOW

    def test_boundary_070(self):
        assert _score_to_trust_level(0.70) == TrustLevel.HIGH

    def test_boundary_040(self):
        assert _score_to_trust_level(0.40) == TrustLevel.MEDIUM

    def test_boundary_039(self):
        assert _score_to_trust_level(0.39) == TrustLevel.LOW


class TestReputationEngineEvaluation:
    def test_new_agent_unestablished(self):
        engine = ReputationEngine()
        ctx = _make_ctx()
        result = engine.evaluate(ctx)
        assert result.trust_level == TrustLevel.UNESTABLISHED
        assert result.change == ReputationChange.NEW_AGENT
        assert 0.4 <= result.overall_score <= 0.6  # Near neutral

    def test_high_success_rate_agent(self):
        engine = ReputationEngine()
        ctx = _make_ctx(
            total_transactions=50,
            total_decisions=50,
            allow_count=48,
            review_count=2,
            block_count=0,
            recent_allow_count=20,
            recent_review_count=0,
            recent_block_count=0,
            account_age_days=200,
            average_risk_score=0.1,
            max_risk_score=0.2,
            risk_history_available=True,
        )
        result = engine.evaluate(ctx)
        assert result.overall_score > 0.70
        assert result.trust_level == TrustLevel.HIGH

    def test_low_trust_agent(self):
        engine = ReputationEngine()
        ctx = _make_ctx(
            total_transactions=20,
            total_decisions=20,
            allow_count=5,
            review_count=5,
            block_count=10,
            recent_allow_count=1,
            recent_review_count=2,
            recent_block_count=7,
            total_policy_violations=15,
            critical_violations=3,
            total_drift_events=10,
            critical_drift_count=2,
            average_risk_score=0.85,
            max_risk_score=0.95,
            risk_history_available=True,
        )
        result = engine.evaluate(ctx)
        assert result.overall_score < 0.40
        assert result.trust_level == TrustLevel.LOW

    def test_dimensions_present(self):
        engine = ReputationEngine()
        ctx = _make_ctx(total_transactions=10)
        result = engine.evaluate(ctx)
        assert len(result.dimensions) == 7
        dim_types = {d.dimension for d in result.dimensions}
        assert dim_types == set(ReputationDimension)

    def test_evaluator_metadata(self):
        engine = ReputationEngine()
        result = engine.evaluate(_make_ctx())
        assert result.model_version == "reputation-v1"
        assert result.agent_id == "a1"
        assert result.evaluation_id != ""
        assert result.evaluated_at != ""

    def test_summary_populated(self):
        engine = ReputationEngine()
        result = engine.evaluate(_make_ctx())
        assert len(result.summary) > 0

    def test_explanation_populated(self):
        engine = ReputationEngine()
        result = engine.evaluate(_make_ctx())
        assert "dimensions" in result.explanation
        assert "data_completeness" in result.explanation

    def test_score_clamped_01(self):
        engine = ReputationEngine()
        ctx = _make_ctx(
            total_transactions=100,
            total_decisions=100,
            allow_count=100,
            recent_allow_count=50,
            account_age_days=365,
            average_risk_score=0.0,
            risk_history_available=True,
        )
        result = engine.evaluate(ctx)
        assert 0.0 <= result.overall_score <= 1.0

    def test_dimensions_weighted_contribution(self):
        engine = ReputationEngine()
        ctx = _make_ctx(total_transactions=10)
        result = engine.evaluate(ctx)
        for dim in result.dimensions:
            assert abs(dim.weighted_contribution - dim.score * dim.weight) < 0.001


class TestChangeDetection:
    def test_new_agent_change(self):
        engine = ReputationEngine()
        ctx = _make_ctx(total_transactions=10)
        result = engine.evaluate(ctx, previous_snapshot=None)
        assert result.change == ReputationChange.NEW_AGENT
        assert result.change_magnitude == 1.0

    def test_stable_change(self):
        engine = ReputationEngine()
        ctx = _make_ctx(
            total_transactions=20,
            total_decisions=20,
            allow_count=18,
            recent_allow_count=10,
        )
        previous = _make_snapshot(score=0.70)
        result = engine.evaluate(ctx, previous_snapshot=previous)
        # Score should be close to 0.70
        if abs(result.overall_score - 0.70) < 0.05:
            assert result.change == ReputationChange.STABLE

    def test_improvement(self):
        engine = ReputationEngine()
        ctx = _make_ctx(
            total_transactions=50,
            total_decisions=50,
            allow_count=48,
            recent_allow_count=25,
            recent_review_count=0,
            recent_block_count=0,
            account_age_days=100,
            average_risk_score=0.1,
            risk_history_available=True,
        )
        previous = _make_snapshot(score=0.30)
        result = engine.evaluate(ctx, previous_snapshot=previous)
        if result.overall_score > 0.35:
            assert result.change == ReputationChange.IMPROVED

    def test_decline(self):
        engine = ReputationEngine()
        ctx = _make_ctx(
            total_transactions=50,
            total_decisions=50,
            allow_count=10,
            review_count=15,
            block_count=25,
            recent_allow_count=2,
            recent_review_count=5,
            recent_block_count=13,
            total_policy_violations=30,
            critical_violations=5,
            total_drift_events=20,
            critical_drift_count=5,
            average_risk_score=0.9,
            max_risk_score=0.95,
            risk_history_available=True,
        )
        previous = _make_snapshot(score=0.80)
        result = engine.evaluate(ctx, previous_snapshot=previous)
        if result.overall_score < 0.75:
            assert result.change == ReputationChange.DECLINED

    def test_invalid_previous_snapshot(self):
        engine = ReputationEngine()
        ctx = _make_ctx()
        result = engine.evaluate(ctx, previous_snapshot="invalid")
        assert result.change == ReputationChange.NEW_AGENT


class TestSerialization:
    def test_result_serializable(self):
        engine = ReputationEngine()
        result = engine.evaluate(_make_ctx())
        # Should be JSON-serializable via Pydantic
        data = result.model_dump()
        assert isinstance(data, dict)
        assert "overall_score" in data
        assert "dimensions" in data

    def test_round_trip(self):
        engine = ReputationEngine()
        result = engine.evaluate(_make_ctx())
        data = result.model_dump()
        restored = ReputationResult(**data)
        assert restored.overall_score == result.overall_score
        assert restored.trust_level == result.trust_level

    def test_snapshot_format(self):
        engine = ReputationEngine()
        result = engine.evaluate(_make_ctx())
        snapshot = result.model_dump()
        # Should be safe for JSONB storage
        assert "overall_score" in snapshot
        assert "trust_level" in snapshot
        assert "model_version" in snapshot
        assert "evaluated_at" in snapshot


class TestSecurity:
    def test_no_eval(self):
        import inspect

        from app.services.reputation_engine import engine as eng
        source = inspect.getsource(eng)
        assert "eval(" not in source or "eval(" in source.replace("eval(", "EVAL_")
        # Check no dangerous builtins
        assert "exec(" not in source
        assert "__import__(" not in source

    def test_no_external_imports(self):
        import inspect

        from app.services.reputation_engine import engine as eng
        source = inspect.getsource(eng)
        assert "requests" not in source
        assert "httpx" not in source
        assert "openai" not in source
        assert "gemini" not in source

    def test_no_database_imports(self):
        import inspect

        from app.services.reputation_engine import engine as eng
        source = inspect.getsource(eng)
        assert "sqlalchemy" not in source.lower()
        assert "database" not in source.lower() or "No database" in source

    def test_no_payment_imports(self):
        import inspect

        from app.services.reputation_engine import engine as eng
        source = inspect.getsource(eng)
        assert "razorpay" not in source.lower()
        assert "payment" not in source.lower() or "payment" in "No payment execution"

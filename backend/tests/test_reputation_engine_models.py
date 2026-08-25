"""Tests for Reputation Engine domain models."""

from app.services.reputation_engine.models import (
    BehavioralContext,
    DimensionScore,
    ReputationChange,
    ReputationDimension,
    ReputationResult,
    TrustLevel,
)

# ── Enum Tests ─────────────────────────────────────────────────────


class TestReputationDimension:
    def test_all_dimensions_exist(self):
        dims = list(ReputationDimension)
        assert len(dims) == 7

    def test_dimension_values(self):
        assert ReputationDimension.SUCCESS_RATE.value == "success_rate"
        assert ReputationDimension.POLICY_COMPLIANCE.value == "policy_compliance"
        assert ReputationDimension.DRIFT_BEHAVIOR.value == "drift_behavior"
        assert ReputationDimension.RISK_PROFILE.value == "risk_profile"
        assert ReputationDimension.CONSISTENCY.value == "consistency"
        assert ReputationDimension.LONGEVITY.value == "longevity"
        assert ReputationDimension.AMOUNT_BEHAVIOR.value == "amount_behavior"


class TestReputationChange:
    def test_all_values(self):
        assert ReputationChange.IMPROVED.value == "improved"
        assert ReputationChange.DECLINED.value == "declined"
        assert ReputationChange.STABLE.value == "stable"
        assert ReputationChange.NEW_AGENT.value == "new_agent"


class TestTrustLevel:
    def test_all_values(self):
        assert TrustLevel.HIGH.value == "high"
        assert TrustLevel.MEDIUM.value == "medium"
        assert TrustLevel.LOW.value == "low"
        assert TrustLevel.UNESTABLISHED.value == "unestablished"


# ── BehavioralContext Tests ────────────────────────────────────────


class TestBehavioralContext:
    def test_default_context(self):
        ctx = BehavioralContext(agent_id="a1", user_id="u1")
        assert ctx.total_transactions == 0
        assert ctx.history_available is False

    def test_full_context(self):
        ctx = BehavioralContext(
            agent_id="a1",
            user_id="u1",
            total_transactions=50,
            allow_count=45,
            review_count=3,
            block_count=2,
            total_decisions=50,
            history_available=True,
        )
        assert ctx.total_transactions == 50
        assert ctx.allow_count == 45

    def test_negative_counts_rejected(self):
        import pydantic
        try:
            BehavioralContext(
                agent_id="a1",
                user_id="u1",
                total_transactions=-1,
            )
            assert False, "Should have raised validation error"
        except pydantic.ValidationError:
            pass


# ── DimensionScore Tests ───────────────────────────────────────────


class TestDimensionScore:
    def test_valid_score(self):
        ds = DimensionScore(
            dimension=ReputationDimension.SUCCESS_RATE,
            score=0.85,
            weight=0.30,
            weighted_contribution=0.255,
            confidence=0.9,
            what="test",
            why="test",
        )
        assert ds.score == 0.85

    def test_score_bounds(self):
        import pydantic
        try:
            DimensionScore(
                dimension=ReputationDimension.SUCCESS_RATE,
                score=1.5,  # Invalid
                weight=0.30,
                weighted_contribution=0.255,
                confidence=0.9,
            )
            assert False, "Should have raised validation error"
        except pydantic.ValidationError:
            pass

    def test_negative_score_rejected(self):
        import pydantic
        try:
            DimensionScore(
                dimension=ReputationDimension.SUCCESS_RATE,
                score=-0.1,  # Invalid
                weight=0.30,
                weighted_contribution=0.0,
                confidence=0.9,
            )
            assert False, "Should have raised validation error"
        except pydantic.ValidationError:
            pass


# ── ReputationResult Tests ─────────────────────────────────────────


class TestReputationResult:
    def test_minimal_result(self):
        r = ReputationResult(
            overall_score=0.5,
            trust_level=TrustLevel.MEDIUM,
            dimensions=[],
            change=ReputationChange.NEW_AGENT,
        )
        assert r.overall_score == 0.5
        assert r.trust_level == TrustLevel.MEDIUM

    def test_result_with_dimensions(self):
        dim = DimensionScore(
            dimension=ReputationDimension.SUCCESS_RATE,
            score=0.8,
            weight=0.30,
            weighted_contribution=0.24,
            confidence=0.9,
        )
        r = ReputationResult(
            overall_score=0.8,
            trust_level=TrustLevel.HIGH,
            dimensions=[dim],
            change=ReputationChange.IMPROVED,
            change_magnitude=0.10,
            change_reasons=["Overall improved"],
        )
        assert len(r.dimensions) == 1
        assert r.change_magnitude == 0.10

    def test_model_version_default(self):
        r = ReputationResult(
            overall_score=0.5,
            trust_level=TrustLevel.MEDIUM,
            dimensions=[],
            change=ReputationChange.NEW_AGENT,
        )
        assert r.model_version == "reputation-v1"
        assert r.feature_version == "v1"

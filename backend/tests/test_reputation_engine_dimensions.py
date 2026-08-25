"""Tests for Reputation Engine dimension scorers."""

from app.services.reputation_engine.constants import DIMENSION_WEIGHTS
from app.services.reputation_engine.dimensions import (
    score_amount_behavior,
    score_consistency,
    score_drift_behavior,
    score_longevity,
    score_policy_compliance,
    score_risk_profile,
    score_success_rate,
)
from app.services.reputation_engine.models import BehavioralContext, ReputationDimension


def _make_ctx(**kwargs) -> BehavioralContext:
    defaults = {"agent_id": "a1", "user_id": "u1"}
    defaults.update(kwargs)
    return BehavioralContext(**defaults)


# ── Success Rate ───────────────────────────────────────────────────


class TestSuccessRate:
    def test_no_decisions_neutral(self):
        dim = score_success_rate(_make_ctx())
        assert dim.score == 0.5
        assert dim.confidence == 0.5
        assert dim.weight == DIMENSION_WEIGHTS[ReputationDimension.SUCCESS_RATE]

    def test_all_allowed(self):
        ctx = _make_ctx(
            total_decisions=10,
            allow_count=10,
            recent_allow_count=5,
            recent_review_count=0,
            recent_block_count=0,
        )
        dim = score_success_rate(ctx)
        assert dim.score == 1.0
        assert dim.confidence == 0.5  # 10/20

    def test_all_blocked(self):
        ctx = _make_ctx(
            total_decisions=10,
            allow_count=0,
            block_count=10,
            recent_allow_count=0,
            recent_block_count=10,
        )
        dim = score_success_rate(ctx)
        assert dim.score == 0.0

    def test_recent_weighted(self):
        ctx = _make_ctx(
            total_decisions=20,
            allow_count=14,
            review_count=4,
            block_count=2,
            recent_allow_count=9,
            recent_review_count=1,
            recent_block_count=0,
        )
        dim = score_success_rate(ctx)
        # recent rate = 9/10 = 0.9, overall = 14/20 = 0.7
        # score = 0.6 * 0.9 + 0.4 * 0.7 = 0.82
        assert abs(dim.score - 0.82) < 0.01
        assert dim.confidence == 1.0

    def test_weighted_contribution(self):
        ctx = _make_ctx(
            total_decisions=20,
            allow_count=20,
            recent_allow_count=10,
        )
        dim = score_success_rate(ctx)
        assert abs(dim.weighted_contribution - dim.score * dim.weight) < 0.001

    def test_boundary_zero_decisions(self):
        dim = score_success_rate(_make_ctx())
        assert dim.evidence["total_decisions"] == 0


# ── Policy Compliance ──────────────────────────────────────────────


class TestPolicyCompliance:
    def test_no_transactions_neutral(self):
        dim = score_policy_compliance(_make_ctx())
        assert dim.score == 0.5
        assert dim.confidence == 0.5

    def test_no_violations_perfect(self):
        ctx = _make_ctx(total_transactions=20)
        dim = score_policy_compliance(ctx)
        assert dim.score == 1.0

    def test_critical_violation_penalty(self):
        ctx = _make_ctx(
            total_transactions=20,
            total_policy_violations=1,
            critical_violations=1,
        )
        dim = score_policy_compliance(ctx)
        # violation_rate = 0.05, base = 1.0 - 0.25 = 0.75
        # critical penalty = 0.15
        # score = 0.75 - 0.15 = 0.60
        assert abs(dim.score - 0.60) < 0.02

    def test_many_violations_floor(self):
        ctx = _make_ctx(
            total_transactions=10,
            total_policy_violations=10,
            critical_violations=5,
        )
        dim = score_policy_compliance(ctx)
        assert dim.score == 0.0

    def test_recent_violations_penalty(self):
        ctx = _make_ctx(
            total_transactions=20,
            total_policy_violations=2,
            recent_policy_violations=2,
        )
        dim = score_policy_compliance(ctx)
        # violation_rate = 0.1, base = 1.0 - 0.5 = 0.5
        # recent penalty = 0.10 * 2 = 0.20
        # score = 0.5 - 0.20 = 0.30
        assert abs(dim.score - 0.30) < 0.02


# ── Drift Behavior ────────────────────────────────────────────────


class TestDriftBehavior:
    def test_no_transactions_neutral(self):
        dim = score_drift_behavior(_make_ctx())
        assert dim.score == 0.5

    def test_no_drift_perfect(self):
        ctx = _make_ctx(total_transactions=20)
        dim = score_drift_behavior(ctx)
        assert dim.score == 1.0

    def test_critical_drift_penalty(self):
        ctx = _make_ctx(
            total_transactions=20,
            total_drift_events=2,
            critical_drift_count=1,
        )
        dim = score_drift_behavior(ctx)
        # drift_rate = 0.1, base = 1.0 - 0.3 = 0.7
        # critical penalty = 0.20
        # score = 0.7 - 0.20 = 0.50
        assert abs(dim.score - 0.50) < 0.02

    def test_many_drifts_floor(self):
        ctx = _make_ctx(
            total_transactions=10,
            total_drift_events=10,
            critical_drift_count=5,
        )
        dim = score_drift_behavior(ctx)
        assert dim.score == 0.0


# ── Risk Profile ───────────────────────────────────────────────────


class TestRiskProfile:
    def test_no_risk_data_neutral(self):
        dim = score_risk_profile(_make_ctx())
        assert dim.score == 0.5
        assert dim.confidence == 0.3

    def test_low_risk_high_score(self):
        ctx = _make_ctx(
            average_risk_score=0.1,
            risk_history_available=True,
        )
        dim = score_risk_profile(ctx)
        assert dim.score == 0.9

    def test_high_risk_low_score(self):
        ctx = _make_ctx(average_risk_score=0.8)
        dim = score_risk_profile(ctx)
        assert dim.score == 0.2  # 1.0 - 0.8

    def test_max_risk_spike_penalty(self):
        ctx = _make_ctx(
            average_risk_score=0.3,
            max_risk_score=0.9,
        )
        dim = score_risk_profile(ctx)
        # score = 1.0 - 0.3 = 0.7, spike penalty = 0.15
        assert abs(dim.score - 0.55) < 0.02

    def test_critical_risk_penalty(self):
        ctx = _make_ctx(
            average_risk_score=0.2,
            critical_risk_count=2,
        )
        dim = score_risk_profile(ctx)
        # score = 1.0 - 0.2 = 0.8, critical penalty = 0.10 * 2 = 0.20
        assert abs(dim.score - 0.60) < 0.02


# ── Consistency ────────────────────────────────────────────────────


class TestConsistency:
    def test_insufficient_data_neutral(self):
        dim = score_consistency(_make_ctx())
        assert dim.score == 0.5
        assert dim.confidence == 0.3

    def test_low_variation_high_score(self):
        ctx = _make_ctx(
            total_transactions=10,
            amount_stddev=5.0,
            average_transaction_amount=50.0,
        )
        dim = score_consistency(ctx)
        # cv = 0.1, score = 1.0 - 0.1/2 = 0.95
        assert abs(dim.score - 0.95) < 0.02

    def test_high_variation_low_score(self):
        ctx = _make_ctx(
            total_transactions=10,
            amount_stddev=100.0,
            average_transaction_amount=50.0,
        )
        dim = score_consistency(ctx)
        # cv = 2.0, score = 1.0 - min(2.0/2, 1.0) = 0.0
        assert dim.score == 0.0


# ── Longevity ──────────────────────────────────────────────────────


class TestLongevity:
    def test_unknown_age(self):
        dim = score_longevity(_make_ctx())
        assert dim.score == 0.3
        assert dim.confidence == 0.3

    def test_new_account(self):
        ctx = _make_ctx(account_age_days=1)
        dim = score_longevity(ctx)
        # sigmoid(0.02 * (1 - 60)) = sigmoid(-1.18) ≈ 0.235
        assert dim.score < 0.4

    def test_established_account(self):
        ctx = _make_ctx(account_age_days=180)
        dim = score_longevity(ctx)
        # sigmoid(0.02 * (180 - 60)) = sigmoid(2.4) ≈ 0.92
        assert dim.score > 0.8

    def test_boundary_zero_days(self):
        ctx = _make_ctx(account_age_days=0)
        dim = score_longevity(ctx)
        # sigmoid(0.02 * (0 - 60)) = sigmoid(-1.2) ≈ 0.23
        assert dim.score < 0.4

    def test_60_day_boundary(self):
        ctx = _make_ctx(account_age_days=60)
        dim = score_longevity(ctx)
        # sigmoid(0) = 0.5
        assert abs(dim.score - 0.5) < 0.02


# ── Amount Behavior ────────────────────────────────────────────────


class TestAmountBehavior:
    def test_insufficient_data_neutral(self):
        dim = score_amount_behavior(_make_ctx())
        assert dim.score == 0.5
        assert dim.confidence == 0.3

    def test_normal_ratio(self):
        ctx = _make_ctx(
            total_transactions=10,
            max_transaction_amount=100.0,
            average_transaction_amount=50.0,
        )
        dim = score_amount_behavior(ctx)
        # ratio = 2.0, score = 1.0 - max(0, (2-3)/10) = 1.0
        assert dim.score == 1.0

    def test_extreme_outlier(self):
        ctx = _make_ctx(
            total_transactions=10,
            max_transaction_amount=1000.0,
            average_transaction_amount=50.0,
        )
        dim = score_amount_behavior(ctx)
        # ratio = 20.0, score = 1.0 - min((20-3)/10, 1.0) = 0.0
        assert dim.score == 0.0

    def test_boundary_ratio_3(self):
        ctx = _make_ctx(
            total_transactions=10,
            max_transaction_amount=150.0,
            average_transaction_amount=50.0,
        )
        dim = score_amount_behavior(ctx)
        # ratio = 3.0, score = 1.0 - max(0, 0) = 1.0
        assert dim.score == 1.0

    def test_boundary_ratio_13(self):
        ctx = _make_ctx(
            total_transactions=10,
            max_transaction_amount=650.0,
            average_transaction_amount=50.0,
        )
        dim = score_amount_behavior(ctx)
        # ratio = 13.0, score = 1.0 - min(10/10, 1.0) = 0.0
        assert dim.score == 0.0


# ── Weight Sum ─────────────────────────────────────────────────────


class TestDimensionWeights:
    def test_weights_sum_to_one(self):
        total = sum(DIMENSION_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_all_weights_positive(self):
        for dim, weight in DIMENSION_WEIGHTS.items():
            assert weight >= 0, f"{dim} has negative weight"

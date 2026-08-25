"""Tests for Reputation Engine feature extraction helpers."""

from app.services.reputation_engine.features import (
    compute_account_age_days,
    compute_amount_outlier_ratio,
    compute_coefficient_of_variation,
    compute_consistency_confidence,
    compute_decision_confidence,
    compute_drift_rate,
    compute_success_rate,
    compute_transaction_confidence,
    compute_violation_rate,
    sigmoid,
)
from app.services.reputation_engine.models import BehavioralContext


def _make_ctx(**kwargs) -> BehavioralContext:
    defaults = {"agent_id": "a1", "user_id": "u1"}
    defaults.update(kwargs)
    return BehavioralContext(**defaults)


class TestComputeSuccessRate:
    def test_no_decisions(self):
        ctx = _make_ctx()
        overall, recent = compute_success_rate(ctx)
        assert overall == 0.5
        assert recent == 0.5

    def test_all_allowed(self):
        ctx = _make_ctx(
            total_decisions=10,
            allow_count=10,
            recent_allow_count=5,
            recent_review_count=0,
            recent_block_count=0,
        )
        overall, recent = compute_success_rate(ctx)
        assert overall == 1.0
        assert recent == 1.0

    def test_mixed_outcomes(self):
        ctx = _make_ctx(
            total_decisions=10,
            allow_count=7,
            review_count=2,
            block_count=1,
            recent_allow_count=3,
            recent_review_count=1,
            recent_block_count=1,
        )
        overall, recent = compute_success_rate(ctx)
        assert abs(overall - 0.7) < 0.01
        assert abs(recent - 0.6) < 0.01

    def test_all_blocked(self):
        ctx = _make_ctx(
            total_decisions=5,
            allow_count=0,
            block_count=5,
            recent_allow_count=0,
            recent_block_count=5,
        )
        overall, recent = compute_success_rate(ctx)
        assert overall == 0.0
        assert recent == 0.0


class TestComputeViolationRate:
    def test_no_transactions(self):
        assert compute_violation_rate(_make_ctx()) == 0.0

    def test_with_violations(self):
        ctx = _make_ctx(total_transactions=20, total_policy_violations=4)
        assert abs(compute_violation_rate(ctx) - 0.2) < 0.01


class TestComputeDriftRate:
    def test_no_transactions(self):
        assert compute_drift_rate(_make_ctx()) == 0.0

    def test_with_drift(self):
        ctx = _make_ctx(total_transactions=10, total_drift_events=3)
        assert abs(compute_drift_rate(ctx) - 0.3) < 0.01


class TestComputeCV:
    def test_insufficient_data(self):
        assert compute_coefficient_of_variation(_make_ctx()) is None

    def test_valid_data(self):
        ctx = _make_ctx(amount_stddev=10.0, average_transaction_amount=50.0)
        cv = compute_coefficient_of_variation(ctx)
        assert cv is not None
        assert abs(cv - 0.2) < 0.01

    def test_zero_average(self):
        ctx = _make_ctx(amount_stddev=10.0, average_transaction_amount=0.0)
        assert compute_coefficient_of_variation(ctx) is None


class TestComputeAmountOutlierRatio:
    def test_insufficient_data(self):
        assert compute_amount_outlier_ratio(_make_ctx()) is None

    def test_valid_data(self):
        ctx = _make_ctx(max_transaction_amount=200.0, average_transaction_amount=50.0)
        ratio = compute_amount_outlier_ratio(ctx)
        assert ratio is not None
        assert abs(ratio - 4.0) < 0.01


class TestComputeAccountAge:
    def test_none(self):
        assert compute_account_age_days(_make_ctx()) is None

    def test_with_age(self):
        ctx = _make_ctx(account_age_days=120)
        assert compute_account_age_days(ctx) == 120


class TestSigmoid:
    def test_zero(self):
        assert abs(sigmoid(0) - 0.5) < 0.01

    def test_large_positive(self):
        assert sigmoid(100) > 0.99

    def test_large_negative(self):
        assert sigmoid(-100) < 0.01

    def test_overflow_positive(self):
        result = sigmoid(1000)
        assert result == 1.0

    def test_overflow_negative(self):
        result = sigmoid(-1000)
        assert result == 0.0


class TestConfidenceFunctions:
    def test_decision_confidence_zero(self):
        assert compute_decision_confidence(0) == 0.0

    def test_decision_confidence_full(self):
        assert compute_decision_confidence(20) == 1.0

    def test_decision_confidence_half(self):
        assert abs(compute_decision_confidence(10) - 0.5) < 0.01

    def test_transaction_confidence_zero(self):
        assert compute_transaction_confidence(0) == 0.0

    def test_transaction_confidence_full(self):
        assert compute_transaction_confidence(10) == 1.0

    def test_consistency_confidence_zero(self):
        assert compute_consistency_confidence(0) == 0.0

    def test_consistency_confidence_full(self):
        assert compute_consistency_confidence(15) == 1.0

"""Tests for Behavioral Engine baseline computation."""


from app.services.behavioral_engine.baseline import (
    AmountBaseline,
    FrequencyBaseline,
    MerchantBaseline,
    build_amount_baseline,
    build_frequency_baseline,
    build_merchant_baseline,
)
from app.services.behavioral_engine.models import AnomalyContext, TransactionRecord


def _make_ctx(transactions: list[dict]) -> AnomalyContext:
    """Helper to build AnomalyContext from dicts."""
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
        history_available=True,
    )


# ── Amount Baseline ────────────────────────────────────────────────


class TestAmountBaseline:
    """Tests for amount baseline computation."""

    def test_empty(self):
        baseline = AmountBaseline([])
        assert baseline.count == 0
        assert baseline.median == 0.0

    def test_single_value(self):
        baseline = AmountBaseline([500.0])
        assert baseline.count == 1
        assert baseline.median == 500.0

    def test_odd_count(self):
        baseline = AmountBaseline([100.0, 200.0, 300.0])
        assert baseline.median == 200.0

    def test_even_count(self):
        baseline = AmountBaseline([100.0, 200.0, 300.0, 400.0])
        assert baseline.median == 250.0

    def test_mad_calculation(self):
        # MAD of [1, 2, 3, 4, 5] with median 3
        # deviations: [2, 1, 0, 1, 2] → sorted [0, 1, 1, 2, 2] → MAD = 1
        baseline = AmountBaseline([1.0, 2.0, 3.0, 4.0, 5.0])
        assert baseline.mad == 1.0

    def test_stddev_fallback(self):
        # When all values are the same, MAD = 0, stddev = 0
        baseline = AmountBaseline([100.0, 100.0, 100.0, 100.0, 100.0])
        assert baseline.mad == 0.0
        assert baseline.stddev == 0.0
        # effective_scale falls back to median * 0.10
        assert baseline.effective_scale == 10.0

    def test_z_score_normal(self):
        baseline = AmountBaseline([100.0, 110.0, 90.0, 105.0, 95.0])
        z = baseline.z_score(100.0)
        assert 0.0 <= z < 1.0  # Within normal range

    def test_z_score_outlier(self):
        baseline = AmountBaseline([100.0, 110.0, 90.0, 105.0, 95.0])
        z = baseline.z_score(500.0)
        assert z > 2.0  # Clearly unusual

    def test_z_score_empty(self):
        baseline = AmountBaseline([])
        z = baseline.z_score(100.0)
        assert z == 0.0

    def test_outlier_resistance(self):
        # One extreme outlier in history shouldn't inflate baseline too much
        baseline = AmountBaseline([100.0, 110.0, 90.0, 105.0, 95.0, 10000.0])
        # Median should still be ~102.5, not affected by 10000
        assert baseline.median < 200.0
        # MAD is resistant to outliers — the outlier doesn't dominate
        # but with only 6 values, MAD may still be affected
        # The key property: median is robust
        assert baseline.median == 102.5


# ── Frequency Baseline ────────────────────────────────────────────


class TestFrequencyBaseline:
    """Tests for frequency baseline computation."""

    def test_empty(self):
        baseline = FrequencyBaseline([])
        assert baseline.count == 0
        assert baseline.mean_interval == 0.0

    def test_single_timestamp(self):
        baseline = FrequencyBaseline(["2025-01-15T10:00:00Z"])
        assert baseline.count == 1
        assert len(baseline.intervals_hours) == 0

    def test_two_timestamps(self):
        baseline = FrequencyBaseline([
            "2025-01-15T10:00:00Z",
            "2025-01-15T12:00:00Z",
        ])
        assert baseline.mean_interval == 2.0

    def test_consistent_intervals(self):
        baseline = FrequencyBaseline([
            "2025-01-15T10:00:00Z",
            "2025-01-15T11:00:00Z",
            "2025-01-15T12:00:00Z",
            "2025-01-15T13:00:00Z",
        ])
        assert baseline.mean_interval == 1.0
        assert baseline.stddev_interval == 0.0

    def test_variable_intervals(self):
        baseline = FrequencyBaseline([
            "2025-01-15T08:00:00Z",
            "2025-01-15T10:00:00Z",  # 2h
            "2025-01-15T11:00:00Z",  # 1h
            "2025-01-15T14:00:00Z",  # 3h
        ])
        assert baseline.mean_interval == 2.0
        assert baseline.stddev_interval > 0.0

    def test_hours_since_last(self):
        baseline = FrequencyBaseline([
            "2025-01-15T10:00:00Z",
            "2025-01-15T12:00:00Z",
        ])
        from datetime import UTC, datetime
        ref = datetime(2025, 1, 15, 14, 0, 0, tzinfo=UTC)
        hours = baseline.hours_since_last(ref)
        assert hours == 2.0

    def test_deterministic_ordering(self):
        """Unordered timestamps produce same result."""
        ts1 = ["2025-01-15T12:00:00Z", "2025-01-15T10:00:00Z", "2025-01-15T11:00:00Z"]
        ts2 = ["2025-01-15T10:00:00Z", "2025-01-15T11:00:00Z", "2025-01-15T12:00:00Z"]
        b1 = FrequencyBaseline(ts1)
        b2 = FrequencyBaseline(ts2)
        assert b1.mean_interval == b2.mean_interval

    def test_malformed_timestamp_handled(self):
        baseline = FrequencyBaseline([
            "2025-01-15T10:00:00Z",
            "not-a-date",
            "2025-01-15T12:00:00Z",
        ])
        # count is total entries, but parsed_timestamps only has valid ones
        assert baseline.count == 3
        assert len(baseline.parsed_timestamps) == 2
        assert baseline.mean_interval == 2.0


# ── Merchant Baseline ─────────────────────────────────────────────


class TestMerchantBaseline:
    """Tests for merchant baseline computation."""

    def test_empty(self):
        baseline = MerchantBaseline([])
        assert baseline.count == 0
        assert len(baseline.known_merchants) == 0

    def test_known_merchant(self):
        baseline = MerchantBaseline(["m1", "m1", "m2"])
        assert baseline.is_known("m1") is True
        assert baseline.is_known("m3") is False

    def test_frequency(self):
        baseline = MerchantBaseline(["m1", "m1", "m2"])
        assert baseline.frequency("m1") == 2 / 3
        assert baseline.frequency("m2") == 1 / 3
        assert baseline.frequency("m3") == 0.0

    def test_none_merchant_handled(self):
        baseline = MerchantBaseline(["m1", None, "m2"])
        assert baseline.is_known(None) is False
        assert baseline.total_with_merchant == 2

    def test_all_none(self):
        baseline = MerchantBaseline([None, None])
        assert baseline.total_with_merchant == 0
        assert baseline.frequency(None) == 0.0


# ── Builder Functions ─────────────────────────────────────────────


class TestBuilderFunctions:
    """Tests for baseline builder functions."""

    def test_build_amount_baseline(self):
        ctx = _make_ctx([
            {"amount": 100.0},
            {"amount": 200.0},
            {"amount": 150.0},
        ])
        baseline = build_amount_baseline(ctx)
        assert baseline.count == 3
        assert baseline.median == 150.0

    def test_build_frequency_baseline(self):
        ctx = _make_ctx([
            {"created_at": "2025-01-15T10:00:00Z"},
            {"created_at": "2025-01-15T12:00:00Z"},
        ])
        baseline = build_frequency_baseline(ctx)
        assert baseline.count == 2
        assert baseline.mean_interval == 2.0

    def test_build_merchant_baseline(self):
        ctx = _make_ctx([
            {"merchant_id": "m1"},
            {"merchant_id": "m1"},
            {"merchant_id": "m2"},
        ])
        baseline = build_merchant_baseline(ctx)
        assert baseline.count == 3
        assert len(baseline.known_merchants) == 2

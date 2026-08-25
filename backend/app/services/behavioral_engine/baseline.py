"""Behavioral baseline computation.

Deterministic calculations for amount, frequency, and merchant baselines.
Pure functions — no I/O, no database, no side effects.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime

from app.services.behavioral_engine.models import AnomalyContext

# ── Amount Baseline ────────────────────────────────────────────────


class AmountBaseline:
    """Agent-specific amount distribution baseline."""

    def __init__(
        self,
        amounts: list[float],
    ) -> None:
        self.count = len(amounts)
        self.amounts = sorted(amounts)
        self.median = self._median(self.amounts)
        self.mad = self._mad(self.amounts, self.median)
        self.stddev = self._stddev(self.amounts)

        # Fallback when both MAD and stddev are zero
        self.effective_scale = self.mad if self.mad > 0 else self.stddev
        if self.effective_scale == 0 and self.median > 0:
            self.effective_scale = self.median * 0.10  # 10% of median
        elif self.effective_scale == 0:
            self.effective_scale = 1.0  # Absolute fallback

    def z_score(self, value: float) -> float:
        """Compute MAD-based z-score for a given amount."""
        if self.count == 0 or self.effective_scale == 0:
            return 0.0
        return abs(value - self.median) / self.effective_scale

    @staticmethod
    def _median(sorted_values: list[float]) -> float:
        if not sorted_values:
            return 0.0
        n = len(sorted_values)
        if n % 2 == 1:
            return sorted_values[n // 2]
        return (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2.0

    @staticmethod
    def _mad(values: list[float], median: float) -> float:
        """Median Absolute Deviation — outlier-resistant scale measure."""
        if not values:
            return 0.0
        deviations = sorted(abs(v - median) for v in values)
        n = len(deviations)
        if n % 2 == 1:
            return deviations[n // 2]
        return (deviations[n // 2 - 1] + deviations[n // 2]) / 2.0

    @staticmethod
    def _stddev(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(variance)


# ── Frequency Baseline ────────────────────────────────────────────


class FrequencyBaseline:
    """Agent-specific transaction frequency baseline."""

    def __init__(
        self,
        timestamps: list[str],
    ) -> None:
        self.count = len(timestamps)
        self.parsed_timestamps = self._parse_and_sort(timestamps)
        self.intervals_hours = self._compute_intervals(self.parsed_timestamps)
        self.mean_interval = self._mean(self.intervals_hours)
        self.stddev_interval = self._stddev(self.intervals_hours)
        self.last_transaction_at = (
            self.parsed_timestamps[-1] if self.parsed_timestamps else None
        )

        # Effective scale for z-score
        self.effective_scale = self.stddev_interval
        if self.effective_scale == 0 and self.mean_interval > 0:
            self.effective_scale = self.mean_interval * 0.10
        elif self.effective_scale == 0:
            self.effective_scale = 1.0

    def hours_since_last(self, reference_time: datetime | None = None) -> float | None:
        """Hours since the last transaction."""
        if self.last_transaction_at is None:
            return None
        if reference_time is None:
            reference_time = datetime.now(UTC)
        delta = reference_time - self.last_transaction_at
        return max(0.0, delta.total_seconds() / 3600.0)

    @staticmethod
    def _parse_and_sort(timestamps: list[str]) -> list[datetime]:
        parsed = []
        for ts in timestamps:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                parsed.append(dt)
            except (ValueError, TypeError):
                continue
        return sorted(parsed)

    @staticmethod
    def _compute_intervals(timestamps: list[datetime]) -> list[float]:
        if len(timestamps) < 2:
            return []
        intervals = []
        for i in range(1, len(timestamps)):
            delta = timestamps[i] - timestamps[i - 1]
            hours = delta.total_seconds() / 3600.0
            intervals.append(max(0.0, hours))
        return intervals

    @staticmethod
    def _mean(values: list[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    @staticmethod
    def _stddev(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(variance)


# ── Merchant Baseline ─────────────────────────────────────────────


class MerchantBaseline:
    """Agent-specific merchant familiarity baseline."""

    def __init__(
        self,
        merchant_ids: list[str | None],
    ) -> None:
        self.count = len(merchant_ids)
        valid = [m for m in merchant_ids if m is not None]
        self.total_with_merchant = len(valid)
        self.known_merchants: set[str] = set(valid)
        self.merchant_counts: Counter[str] = Counter(valid)

    def is_known(self, merchant_id: str | None) -> bool:
        """Check if this merchant is in the agent's history."""
        if merchant_id is None:
            return False
        return merchant_id in self.known_merchants

    def frequency(self, merchant_id: str | None) -> float:
        """Get the relative frequency of this merchant in the agent's history."""
        if merchant_id is None or self.total_with_merchant == 0:
            return 0.0
        return self.merchant_counts.get(merchant_id, 0) / self.total_with_merchant


# ── Builder Functions ─────────────────────────────────────────────


def build_amount_baseline(ctx: AnomalyContext) -> AmountBaseline:
    """Build amount baseline from behavioral context."""
    amounts = [t.amount for t in ctx.transactions if t.amount > 0]
    return AmountBaseline(amounts)


def build_frequency_baseline(ctx: AnomalyContext) -> FrequencyBaseline:
    """Build frequency baseline from behavioral context."""
    timestamps = [t.created_at for t in ctx.transactions if t.created_at]
    return FrequencyBaseline(timestamps)


def build_merchant_baseline(ctx: AnomalyContext) -> MerchantBaseline:
    """Build merchant baseline from behavioral context."""
    merchant_ids = [t.merchant_id for t in ctx.transactions]
    return MerchantBaseline(merchant_ids)

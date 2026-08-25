"""Behavioral Baseline Engine — deterministic, explainable anomaly detection.

Compares each transaction against the agent's own historical behavioral
pattern to detect deviations. Agent-specific, not global thresholds.

No database. No API calls. No LLM. No payment execution.
Does NOT make ALLOW/REVIEW/BLOCK decisions.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import structlog

from app.services.behavioral_engine.baseline import (
    AmountBaseline,
    FrequencyBaseline,
    MerchantBaseline,
    build_amount_baseline,
    build_frequency_baseline,
    build_merchant_baseline,
)
from app.services.behavioral_engine.constants import (
    AMOUNT_Z_THRESHOLDS,
    BEHAVIORAL_MODEL_VERSION,
    CONFIDENCE_BY_SAMPLE_SIZE,
    FREQUENCY_LONG_MULTIPLIER,
    FREQUENCY_LONG_SCORE,
    FREQUENCY_SHORT_MULTIPLIER,
    FREQUENCY_SHORT_SCORE,
    MERCHANT_COMMON_SCORE,
    MERCHANT_COMMON_THRESHOLD,
    MERCHANT_FREQUENT_SCORE,
    MERCHANT_FREQUENT_THRESHOLD,
    MERCHANT_NEW_SCORE,
    MERCHANT_RARE_SCORE,
    MIN_SAMPLES_FOR_AMOUNT,
    MIN_SAMPLES_FOR_FREQUENCY,
)
from app.services.behavioral_engine.models import (
    AnomalyContext,
    AnomalyDimension,
    BehavioralAnomalyResult,
    DimensionAnomaly,
)

logger = structlog.get_logger()


class BehavioralBaselineEngine:
    """Deterministic behavioral anomaly engine. No I/O, no DB, no LLM.

    Usage:
        engine = BehavioralBaselineEngine()
        result = engine.evaluate(context)
    """

    def evaluate(self, context: AnomalyContext) -> BehavioralAnomalyResult:
        """Evaluate behavioral anomalies against the agent's historical baseline.

        Args:
            context: Pre-built AnomalyContext with historical transactions.

        Returns:
            BehavioralAnomalyResult with scores, dimensions, and explanation.
        """
        start_time = time.monotonic()
        evaluation_id = str(uuid.uuid4())[:8]
        now = datetime.now(UTC)

        log = logger.bind(
            evaluation_id=evaluation_id,
            agent_id=context.agent_id,
            user_id=context.user_id,
        )

        # Step 1: Build baselines
        amount_baseline = build_amount_baseline(context)
        frequency_baseline = build_frequency_baseline(context)
        merchant_baseline = build_merchant_baseline(context)

        # Step 2: Evaluate each dimension
        dimensions: list[DimensionAnomaly] = []

        amount_dim = self._evaluate_amount(context, amount_baseline)
        if amount_dim is not None:
            dimensions.append(amount_dim)

        freq_dim = self._evaluate_frequency(context, frequency_baseline)
        if freq_dim is not None:
            dimensions.append(freq_dim)

        merchant_dim = self._evaluate_merchant(context, merchant_baseline)
        if merchant_dim is not None:
            dimensions.append(merchant_dim)

        # Step 3: Compute overall score (dominant dimension)
        overall_score = self._compute_overall_score(dimensions)

        # Step 4: Compute confidence
        confidence = self._compute_confidence(context, dimensions)

        # Step 5: Build summary
        summary = self._build_summary(dimensions, overall_score)

        latency_ms = int((time.monotonic() - start_time) * 1000)

        log.info(
            "behavioral_anomaly_completed",
            overall_score=overall_score,
            confidence=confidence,
            dimension_count=len(dimensions),
            sample_size=context.transactions.__len__(),
            model_version=BEHAVIORAL_MODEL_VERSION,
            latency_ms=latency_ms,
        )

        sample_count = len(context.transactions)

        return BehavioralAnomalyResult(
            overall_score=round(overall_score, 4),
            confidence=round(confidence, 4),
            dimensions=dimensions,
            dimension_count=len(dimensions),
            baseline_sample_size=sample_count,
            baseline_history_days=context.history_window_days,
            summary=summary,
            evaluation_id=evaluation_id,
            model_version=BEHAVIORAL_MODEL_VERSION,
            evaluated_at=now.isoformat(),
        )

    # ── Amount Evaluation ──────────────────────────────────────────

    def _evaluate_amount(
        self, ctx: AnomalyContext, baseline: AmountBaseline
    ) -> DimensionAnomaly | None:
        """Evaluate amount anomaly against agent's historical baseline."""
        if ctx.proposal_amount is None:
            return None

        if baseline.count < MIN_SAMPLES_FOR_AMOUNT:
            return DimensionAnomaly(
                dimension=AnomalyDimension.AMOUNT,
                score=0.0,
                confidence=0.0,
                what=(
                    f"Agent has only {baseline.count} historical transactions "
                    f"(need {MIN_SAMPLES_FOR_AMOUNT} for amount baseline)"
                ),
                why="Insufficient history to assess amount anomaly",
                evidence={
                    "sample_size": baseline.count,
                    "required": MIN_SAMPLES_FOR_AMOUNT,
                },
                baseline_used="Insufficient data",
            )

        current = ctx.proposal_amount
        z_score = baseline.z_score(current)

        # Map z-score to anomaly score
        score = 0.0
        for threshold, s in AMOUNT_Z_THRESHOLDS:
            if z_score < threshold:
                score = s
                break

        confidence = _lookup_confidence(baseline.count, CONFIDENCE_BY_SAMPLE_SIZE)

        what = (
            f"Current amount ₹{current:.2f} vs agent's median "
            f"₹{baseline.median:.2f} (MAD: ₹{baseline.mad:.2f}, "
            f"z-score: {z_score:.2f})"
        )

        if score > 0:
            why = (
                f"Amount deviates {z_score:.1f} standard deviations from "
                f"the agent's historical pattern"
            )
        else:
            why = "Amount is within the agent's normal range"

        return DimensionAnomaly(
            dimension=AnomalyDimension.AMOUNT,
            score=round(score, 4),
            confidence=round(confidence, 4),
            what=what,
            why=why,
            evidence={
                "current_amount": current,
                "median": round(baseline.median, 4),
                "mad": round(baseline.mad, 4),
                "stddev": round(baseline.stddev, 4),
                "z_score": round(z_score, 4),
                "sample_size": baseline.count,
            },
            baseline_used=(
                f"{baseline.count} transactions, "
                f"median ₹{baseline.median:.2f}"
            ),
        )

    # ── Frequency Evaluation ───────────────────────────────────────

    def _evaluate_frequency(
        self, ctx: AnomalyContext, baseline: FrequencyBaseline
    ) -> DimensionAnomaly | None:
        """Evaluate frequency anomaly against agent's historical rhythm."""
        if baseline.count < MIN_SAMPLES_FOR_FREQUENCY:
            return DimensionAnomaly(
                dimension=AnomalyDimension.FREQUENCY,
                score=0.0,
                confidence=0.0,
                what=(
                    f"Agent has only {baseline.count} historical transactions "
                    f"(need {MIN_SAMPLES_FOR_FREQUENCY} for frequency baseline)"
                ),
                why="Insufficient history to assess frequency anomaly",
                evidence={
                    "sample_size": baseline.count,
                    "required": MIN_SAMPLES_FOR_FREQUENCY,
                },
                baseline_used="Insufficient data",
            )

        hours_since = baseline.hours_since_last()
        if hours_since is None:
            return None

        mean_interval = baseline.mean_interval
        score = 0.0

        if mean_interval > 0:
            ratio = hours_since / mean_interval

            if ratio < FREQUENCY_SHORT_MULTIPLIER:
                # Much more frequent than usual
                scale = FREQUENCY_SHORT_MULTIPLIER / max(ratio, 0.01)
                score = min(FREQUENCY_SHORT_SCORE * scale, 0.60)
            elif ratio > FREQUENCY_LONG_MULTIPLIER:
                # Much less frequent (less risky)
                score = FREQUENCY_LONG_SCORE
            else:
                score = 0.0

        confidence = _lookup_confidence(baseline.count, CONFIDENCE_BY_SAMPLE_SIZE)

        what = (
            f"Current interval: {hours_since:.1f}h since last transaction "
            f"(agent average: {mean_interval:.1f}h)"
        )

        if score > 0:
            if hours_since < mean_interval * FREQUENCY_SHORT_MULTIPLIER:
                why = "Transaction is unusually frequent for this agent"
            else:
                why = "Transaction timing deviates from agent's rhythm"
        else:
            why = "Transaction frequency is within the agent's normal range"

        return DimensionAnomaly(
            dimension=AnomalyDimension.FREQUENCY,
            score=round(score, 4),
            confidence=round(confidence, 4),
            what=what,
            why=why,
            evidence={
                "hours_since_last": round(hours_since, 4),
                "mean_interval_hours": round(mean_interval, 4),
                "stddev_interval_hours": round(baseline.stddev_interval, 4),
                "sample_size": baseline.count,
            },
            baseline_used=(
                f"{len(baseline.intervals_hours)} intervals over "
                f"{baseline.count} transactions"
            ),
        )

    # ── Merchant Evaluation ────────────────────────────────────────

    def _evaluate_merchant(
        self, ctx: AnomalyContext, baseline: MerchantBaseline
    ) -> DimensionAnomaly | None:
        """Evaluate merchant familiarity against agent's history."""
        if baseline.count == 0:
            return DimensionAnomaly(
                dimension=AnomalyDimension.MERCHANT,
                score=0.0,
                confidence=0.0,
                what="No historical transactions for merchant baseline",
                why="No merchant history to compare against",
                evidence={"sample_size": 0},
                baseline_used="No data",
            )

        merchant_id = ctx.proposal_merchant_id
        freq = baseline.frequency(merchant_id)

        if baseline.is_known(merchant_id):
            if freq >= MERCHANT_FREQUENT_THRESHOLD:
                score = MERCHANT_FREQUENT_SCORE
            elif freq >= MERCHANT_COMMON_THRESHOLD:
                score = MERCHANT_COMMON_SCORE
            else:
                score = MERCHANT_RARE_SCORE
        else:
            score = MERCHANT_NEW_SCORE

        confidence = _lookup_confidence(baseline.count, CONFIDENCE_BY_SAMPLE_SIZE)

        merchant_display = merchant_id or "unknown"

        if baseline.is_known(merchant_id):
            what = (
                f"Merchant {merchant_display} is known to this agent "
                f"({freq:.0%} of historical transactions)"
            )
            if score > 0:
                why = "Merchant is known but rarely used by this agent"
            else:
                why = "Merchant is familiar and frequently used by this agent"
        else:
            what = (
                f"Merchant {merchant_display} is NEW — not found in "
                f"agent's {baseline.total_with_merchant} historical transactions "
                f"across {len(baseline.known_merchants)} unique merchants"
            )
            why = "Agent has not transacted with this merchant before"

        return DimensionAnomaly(
            dimension=AnomalyDimension.MERCHANT,
            score=round(score, 4),
            confidence=round(confidence, 4),
            what=what,
            why=why,
            evidence={
                "merchant_id": merchant_display,
                "is_known": baseline.is_known(merchant_id),
                "frequency": round(freq, 4),
                "known_merchant_count": len(baseline.known_merchants),
                "total_transactions": baseline.total_with_merchant,
            },
            baseline_used=(
                f"{baseline.total_with_merchant} transactions across "
                f"{len(baseline.known_merchants)} unique merchants"
            ),
        )

    # ── Overall Score ──────────────────────────────────────────────

    def _compute_overall_score(self, dimensions: list[DimensionAnomaly]) -> float:
        """Compute overall anomaly score using dominant dimension."""
        if not dimensions:
            return 0.0
        return max(d.score for d in dimensions)

    # ── Confidence ─────────────────────────────────────────────────

    def _compute_confidence(
        self,
        ctx: AnomalyContext,
        dimensions: list[DimensionAnomaly],
    ) -> float:
        """Compute confidence based on sample size and dimension availability."""
        sample_count = len(ctx.transactions)

        # Base confidence from sample size
        data_confidence = _lookup_confidence(
            sample_count, CONFIDENCE_BY_SAMPLE_SIZE
        )

        # Blend with average dimension confidence
        if dimensions:
            avg_dim_confidence = (
                sum(d.confidence for d in dimensions) / len(dimensions)
            )
            confidence = data_confidence * 0.6 + avg_dim_confidence * 0.4
        else:
            confidence = data_confidence * 0.5

        return round(max(0.0, min(1.0, confidence)), 4)

    # ── Summary ────────────────────────────────────────────────────

    def _build_summary(
        self, dimensions: list[DimensionAnomaly], overall_score: float
    ) -> str:
        if not dimensions:
            return "No behavioral data available for anomaly analysis."

        contributing = [d for d in dimensions if d.score > 0]
        if not contributing:
            return (
                f"Behavioral analysis ({overall_score:.2f}) — "
                "transaction is consistent with agent's historical pattern."
            )

        descriptions = [d.what for d in contributing]
        return (
            f"Behavioral anomaly ({overall_score:.2f}) — "
            f"{'; '.join(descriptions)}"
        )


# ── Helper ─────────────────────────────────────────────────────────


def _lookup_confidence(
    count: int,
    thresholds: list[tuple[int, float]],
) -> float:
    result = 0.0
    for threshold, conf in thresholds:
        if count >= threshold:
            result = conf
        else:
            break
    return result

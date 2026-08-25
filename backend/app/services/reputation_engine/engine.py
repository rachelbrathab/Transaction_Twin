"""Reputation Engine — deterministic agent behavioral reputation.

Evaluates pre-computed BehavioralContext to produce a ReputationResult.
No database. No API calls. No LLM. No payment execution.
Does NOT make risk or decision judgments.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import structlog

from app.services.reputation_engine.constants import (
    CHANGE_STABLE_THRESHOLD,
    REPUTATION_FEATURE_VERSION,
    REPUTATION_MODEL_VERSION,
    TRUST_LEVEL_THRESHOLDS,
)
from app.services.reputation_engine.dimensions import (
    score_amount_behavior,
    score_consistency,
    score_drift_behavior,
    score_longevity,
    score_policy_compliance,
    score_risk_profile,
    score_success_rate,
)
from app.services.reputation_engine.models import (
    BehavioralContext,
    DimensionScore,
    ReputationChange,
    ReputationResult,
    TrustLevel,
)

logger = structlog.get_logger()

# Ordered list of dimension scorers — deterministic evaluation order
_DIMENSION_SCORERS = [
    score_success_rate,
    score_policy_compliance,
    score_drift_behavior,
    score_risk_profile,
    score_consistency,
    score_longevity,
    score_amount_behavior,
]


def _score_to_trust_level(score: float) -> TrustLevel:
    """Map a reputation score to a trust level."""
    for threshold, level in TRUST_LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return TrustLevel.LOW


def _compute_change(
    previous_score: float | None,
    current_score: float,
) -> tuple[ReputationChange, float, list[str]]:
    """Detect reputation change from previous snapshot.

    Returns (change_direction, magnitude, reasons).
    """
    if previous_score is None:
        return ReputationChange.NEW_AGENT, 1.0, ["New agent -- no previous reputation"]

    delta = current_score - previous_score
    magnitude = abs(delta)

    if magnitude < CHANGE_STABLE_THRESHOLD:
        return ReputationChange.STABLE, magnitude, []

    reasons: list[str] = []

    if delta > 0:
        change = ReputationChange.IMPROVED
        reasons.append(
            f"Overall reputation improved from {previous_score:.2f} to {current_score:.2f}"
        )
    else:
        change = ReputationChange.DECLINED
        reasons.append(
            f"Overall reputation declined from {previous_score:.2f} to {current_score:.2f}"
        )

    return change, round(magnitude, 4), reasons


def _compute_dimension_change_reasons(
    current_dims: list[DimensionScore],
    previous_dims: list[DimensionScore] | None,
) -> list[str]:
    """Compare dimensions and generate change reasons for significant shifts."""
    if previous_dims is None:
        return []

    prev_map = {d.dimension: d.score for d in previous_dims}
    reasons: list[str] = []

    for dim in current_dims:
        prev_score = prev_map.get(dim.dimension)
        if prev_score is not None:
            delta = dim.score - prev_score
            if abs(delta) >= 0.10:
                direction = "improved" if delta > 0 else "declined"
                reasons.append(
                    f"{dim.dimension.value} {direction} from "
                    f"{prev_score:.2f} to {dim.score:.2f}"
                )

    return reasons


def _build_summary(
    trust_level: TrustLevel,
    score: float,
    dimensions: list[DimensionScore],
) -> str:
    """Build human-readable summary."""
    top_dims = sorted(dimensions, key=lambda d: d.weighted_contribution, reverse=True)
    top_names = [d.dimension.value for d in top_dims[:3] if d.weighted_contribution > 0]

    if not top_names:
        return (
            f"{trust_level.value.title()} reputation ({score:.2f}). "
            "Insufficient behavioral data for detailed assessment."
        )

    return (
        f"{trust_level.value.title()} reputation ({score:.2f}) "
        f"driven by: {', '.join(top_names)}"
    )


class ReputationEngine:
    """Deterministic reputation engine. No I/O, no DB, no LLM.

    Usage:
        engine = ReputationEngine()
        result = engine.evaluate(context, previous_snapshot=None)
    """

    def evaluate(
        self,
        context: BehavioralContext,
        previous_snapshot: dict | None = None,
    ) -> ReputationResult:
        """Evaluate behavioral context and produce a deterministic reputation.

        Args:
            context: Pre-built BehavioralContext with all available signals.
            previous_snapshot: Previous reputation snapshot (dict from Agent.reputation_snapshot),
                or None for new agents.

        Returns:
            ReputationResult with score, dimensions, change detection, and explanation.
        """
        start_time = time.monotonic()
        evaluation_id = str(uuid.uuid4())[:8]
        now = datetime.now(UTC)

        log = logger.bind(
            evaluation_id=evaluation_id,
            agent_id=context.agent_id,
            user_id=context.user_id,
        )

        # Step 1: Extract previous reputation if available
        previous_score: float | None = None
        previous_dimensions: list[DimensionScore] | None = None

        if previous_snapshot and isinstance(previous_snapshot, dict):
            previous_score = previous_snapshot.get("overall_score")
            raw_dims = previous_snapshot.get("dimensions", [])
            if isinstance(raw_dims, list):
                try:
                    previous_dimensions = [
                        DimensionScore(**d) for d in raw_dims if isinstance(d, dict)
                    ]
                except Exception:
                    previous_dimensions = None

        # Step 2: Score all dimensions
        dimensions: list[DimensionScore] = []
        for scorer in _DIMENSION_SCORERS:
            dim_score = scorer(context)
            dimensions.append(dim_score)

        # Step 3: Aggregate overall score
        # Weighted average using only dimensions with sufficient confidence
        total_weight = 0.0
        weighted_sum = 0.0
        for dim in dimensions:
            if dim.confidence >= 0.3:
                weighted_sum += dim.weighted_contribution
                total_weight += dim.weight

        if total_weight > 0:
            overall_score = weighted_sum / total_weight
        else:
            overall_score = 0.5  # Neutral when no confident dimensions

        overall_score = round(max(0.0, min(1.0, overall_score)), 4)

        # Step 4: Determine trust level
        # New agents with no transaction history are unestablished
        has_meaningful_history = context.total_transactions > 0
        all_dimensions_neutral = all(
            d.score == 0.5 for d in dimensions
            if d.confidence > 0.3
        )
        if not has_meaningful_history and all_dimensions_neutral:
            trust_level = TrustLevel.UNESTABLISHED
        else:
            trust_level = _score_to_trust_level(overall_score)

        # Step 5: Change detection
        change, change_magnitude, change_reasons = _compute_change(
            previous_score, overall_score
        )

        # Add dimension-level change reasons
        dim_change_reasons = _compute_dimension_change_reasons(
            dimensions, previous_dimensions
        )
        change_reasons.extend(dim_change_reasons)

        # Step 6: Build explanation
        explanation = _build_explanation(context, dimensions, change, change_magnitude)

        # Step 7: Build summary
        summary = _build_summary(trust_level, overall_score, dimensions)

        latency_ms = int((time.monotonic() - start_time) * 1000)

        log.info(
            "reputation_computed",
            trust_level=trust_level.value,
            overall_score=overall_score,
            change=change.value,
            change_magnitude=change_magnitude,
            dimension_count=len(dimensions),
            model_version=REPUTATION_MODEL_VERSION,
            latency_ms=latency_ms,
        )

        if change == ReputationChange.DECLINED and change_magnitude >= 0.15:
            log.warning(
                "reputation_significant_change",
                agent_id=context.agent_id,
                previous_score=previous_score,
                current_score=overall_score,
                change_magnitude=change_magnitude,
            )

        if trust_level == TrustLevel.LOW:
            log.warning(
                "reputation_low_trust",
                agent_id=context.agent_id,
                overall_score=overall_score,
            )

        if change == ReputationChange.NEW_AGENT:
            log.info(
                "reputation_new_agent",
                agent_id=context.agent_id,
            )

        return ReputationResult(
            overall_score=overall_score,
            trust_level=trust_level,
            dimensions=dimensions,
            previous_score=previous_score,
            change=change,
            change_magnitude=change_magnitude,
            change_reasons=change_reasons,
            summary=summary,
            explanation=explanation,
            evaluation_id=evaluation_id,
            agent_id=context.agent_id,
            evaluated_at=now.isoformat(),
            history_window_days=90,
            model_version=REPUTATION_MODEL_VERSION,
            feature_version=REPUTATION_FEATURE_VERSION,
        )


def _build_explanation(
    context: BehavioralContext,
    dimensions: list[DimensionScore],
    change: ReputationChange,
    change_magnitude: float,
) -> dict:
    """Build structured explanation for frontend rendering."""
    explanation: dict = {}

    # Dimensions summary
    explanation["dimensions"] = {
        dim.dimension.value: {
            "score": dim.score,
            "weight": dim.weight,
            "weighted_contribution": dim.weighted_contribution,
            "confidence": dim.confidence,
            "what": dim.what,
            "why": dim.why,
        }
        for dim in dimensions
    }

    # Data availability
    explanation["data_completeness"] = {
        "history_available": context.history_available,
        "decision_history_available": context.decision_history_available,
        "risk_history_available": context.risk_history_available,
        "total_transactions": context.total_transactions,
        "total_decisions": context.total_decisions,
    }

    # Change info
    explanation["change"] = {
        "direction": change.value,
        "magnitude": change_magnitude,
    }

    return explanation

"""Risk Engine aggregator.

Handles correlation groups, weighted scoring, dominant signal boost,
confidence computation, and risk level mapping.
"""

from __future__ import annotations

from app.services.risk_engine.constants import (
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    CONFIDENCE_REDUCTIONS,
    CORRELATION_GROUPS,
    DOMINANT_SIGNAL_MAX_WEIGHT,
    DOMINANT_SIGNAL_MEAN_WEIGHT,
    DOMINANT_SIGNAL_THRESHOLD,
    GROUP_DISCOUNTS,
    RISK_LEVEL_THRESHOLDS,
    SIGNAL_WEIGHTS,
)
from app.services.risk_engine.models import (
    RiskContext,
    RiskEvidence,
    RiskLevel,
    RiskSignalType,
)


def apply_correlation_groups(signals: list[RiskEvidence]) -> list[RiskEvidence]:
    """Apply diminishing-returns discount within correlation groups.

    Signals are sorted deterministically by signal_type before grouping
    to ensure order-independent results.
    """
    # Sort by signal_type value for deterministic ordering
    sorted_signals = sorted(signals, key=lambda s: s.signal_type.value)

    group_counts: dict[str, int] = {}
    result: list[RiskEvidence] = []

    for signal in sorted_signals:
        group = _find_group(signal.signal_type)
        if group is not None:
            count = group_counts.get(group, 0)
            discounts = GROUP_DISCOUNTS.get(group, [1.0])
            discount = discounts[min(count, len(discounts) - 1)]
            # Create a copy with discounted contribution
            modified = signal.model_copy(
                update={"risk_contribution": round(signal.risk_contribution * discount, 4)}
            )
            result.append(modified)
            group_counts[group] = count + 1
        else:
            result.append(signal)

    return result


def compute_weighted_score(signals: list[RiskEvidence]) -> float:
    """Compute normalized weighted score from signals.

    Weights of unavailable signals are redistributed proportionally.
    DATA_QUALITY (weight 0.0) is excluded from scoring.
    """
    available_weight = 0.0
    weighted_sum = 0.0

    for signal in signals:
        weight = SIGNAL_WEIGHTS.get(signal.signal_type, 0.0)
        if weight <= 0:
            continue
        available_weight += weight
        weighted_sum += signal.risk_contribution * weight

    if available_weight <= 0:
        return 0.0

    return weighted_sum / available_weight


def apply_dominant_boost(
    score: float, signals: list[RiskEvidence]
) -> float:
    """Apply dominant-signal boost when a single signal dominates.

    If any post-correlation signal has contribution >= threshold,
    the overall score becomes a blend of max signal and mean score.
    """
    max_contribution = max(
        (s.risk_contribution for s in signals), default=0.0
    )

    if max_contribution >= DOMINANT_SIGNAL_THRESHOLD:
        mean_score = score
        boosted = (
            DOMINANT_SIGNAL_MAX_WEIGHT * max_contribution
            + DOMINANT_SIGNAL_MEAN_WEIGHT * mean_score
        )
        return min(boosted, 1.0)

    return score


def compute_confidence(ctx: RiskContext, signals: list[RiskEvidence]) -> float:
    """Compute confidence based on data availability and signal quality.

    70% context completeness + 30% average signal confidence.
    """
    confidence = 1.0

    # Reduce for missing critical signals
    if not ctx.drift_available:
        confidence -= CONFIDENCE_REDUCTIONS["drift_missing"]
    if ctx.agent_trust_score is None:
        confidence -= CONFIDENCE_REDUCTIONS["agent_trust_missing"]
    if ctx.merchant_trust_score is None and ctx.proposal_merchant_trusted is None:
        confidence -= CONFIDENCE_REDUCTIONS["merchant_trust_missing"]
    if ctx.velocity is None or not ctx.velocity.history_available:
        confidence -= CONFIDENCE_REDUCTIONS["velocity_missing"]
    if ctx.intent_confidence is None:
        confidence -= CONFIDENCE_REDUCTIONS["intent_confidence_missing"]
    if not ctx.policy_available:
        confidence -= CONFIDENCE_REDUCTIONS["policy_missing"]
    if ctx.proposal_amount is None:
        confidence -= CONFIDENCE_REDUCTIONS["proposal_amount_missing"]

    confidence = max(CONFIDENCE_FLOOR, confidence)

    # Blend with average signal confidence
    if signals:
        avg_signal_confidence = sum(s.confidence for s in signals) / len(signals)
        confidence = confidence * 0.7 + avg_signal_confidence * 0.3

    return round(max(CONFIDENCE_FLOOR, min(CONFIDENCE_CEILING, confidence)), 4)


def score_to_level(score: float) -> RiskLevel:
    """Map overall score to risk level using deterministic-v1 thresholds."""
    for threshold, level in RISK_LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return RiskLevel.LOW


def _find_group(signal_type: RiskSignalType) -> str | None:
    """Find which correlation group a signal type belongs to."""
    for group_name, members in CORRELATION_GROUPS.items():
        if signal_type in members:
            return group_name
    return None

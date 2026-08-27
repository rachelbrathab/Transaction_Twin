"""Risk Engine aggregator.

Handles correlation groups, weighted scoring, dominant signal boost,
confidence computation, and risk level mapping.
"""

from __future__ import annotations

from app.services.risk_engine.config import (
    RiskEngineConfig,
    get_effective_confidence_ceiling,
    get_effective_confidence_floor,
    get_effective_confidence_reduction,
    get_effective_risk_level_thresholds,
    get_effective_signal_weight,
)
from app.services.risk_engine.constants import (
    CORRELATION_GROUPS,
    DOMINANT_SIGNAL_MAX_WEIGHT,
    DOMINANT_SIGNAL_MEAN_WEIGHT,
    DOMINANT_SIGNAL_THRESHOLD,
    GROUP_DISCOUNTS,
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


def compute_weighted_score(
    signals: list[RiskEvidence],
    config: RiskEngineConfig | None = None,
) -> float:
    """Compute normalized weighted score from signals.

    Weights of unavailable signals are redistributed proportionally.
    DATA_QUALITY (weight 0.0) is excluded from scoring.

    Args:
        signals: Risk evidence signals.
        config: Optional runtime config overrides. When None, uses defaults.
    """
    available_weight = 0.0
    weighted_sum = 0.0

    for signal in signals:
        weight = get_effective_signal_weight(signal.signal_type, config)
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


def compute_confidence(
    ctx: RiskContext,
    signals: list[RiskEvidence],
    config: RiskEngineConfig | None = None,
) -> float:
    """Compute confidence based on data availability and signal quality.

    70% context completeness + 30% average signal confidence.

    Args:
        ctx: Risk context with signal availability flags.
        signals: Risk evidence signals.
        config: Optional runtime config overrides. When None, uses defaults.
    """
    confidence = 1.0
    cr = lambda key: get_effective_confidence_reduction(key, config)  # noqa: E731

    # Reduce for missing critical signals
    if not ctx.drift_available:
        confidence -= cr("drift_missing")
    if ctx.agent_trust_score is None:
        confidence -= cr("agent_trust_missing")
    if ctx.merchant_trust_score is None and ctx.proposal_merchant_trusted is None:
        confidence -= cr("merchant_trust_missing")
    if ctx.velocity is None or not ctx.velocity.history_available:
        confidence -= cr("velocity_missing")
    if ctx.intent_confidence is None:
        confidence -= cr("intent_confidence_missing")
    if not ctx.policy_available:
        confidence -= cr("policy_missing")
    if ctx.proposal_amount is None:
        confidence -= cr("proposal_amount_missing")

    # Sprint 9: Network risk confidence reductions
    # Network risk reduces confidence when concerning patterns are found.
    # This is the primary integration mechanism — network risk does NOT
    # enter the weighted signal scoring to preserve Sprint 7/8 calibration.
    if ctx.network_risk_available:
        if (
            ctx.network_risk_shared_exposure_score is not None
            and ctx.network_risk_shared_exposure_score > 0.10
        ):
            confidence -= cr("network_shared_risk")
        if (
            ctx.network_risk_concentration_score is not None
            and ctx.network_risk_concentration_score > 0.10
        ):
            confidence -= cr("network_concentration")
        if (
            ctx.network_risk_cluster_risk_score is not None
            and ctx.network_risk_cluster_risk_score > 0.10
        ):
            confidence -= cr("network_cluster_risk")

    # Sprint 10: Behavioral anomaly confidence reductions
    # Behavioral anomaly reduces confidence when concerning patterns are found.
    # Does NOT enter weighted signal scoring — preserves Sprint 7/8/9 calibration.
    if ctx.behavioral_anomaly_available:
        if (
            ctx.behavioral_anomaly_amount_score is not None
            and ctx.behavioral_anomaly_amount_score > 0.10
        ):
            confidence -= cr("behavioral_amount_anomaly")
        if (
            ctx.behavioral_anomaly_frequency_score is not None
            and ctx.behavioral_anomaly_frequency_score > 0.10
        ):
            confidence -= cr("behavioral_frequency_anomaly")
        if (
            ctx.behavioral_anomaly_merchant_score is not None
            and ctx.behavioral_anomaly_merchant_score > 0.10
        ):
            confidence -= cr("behavioral_merchant_anomaly")

    confidence_floor = get_effective_confidence_floor(config)
    confidence_ceiling = get_effective_confidence_ceiling(config)
    confidence = max(confidence_floor, confidence)

    # Blend with average signal confidence
    if signals:
        avg_signal_confidence = sum(s.confidence for s in signals) / len(signals)
        confidence = confidence * 0.7 + avg_signal_confidence * 0.3

    return round(max(confidence_floor, min(confidence_ceiling, confidence)), 4)


def score_to_level(
    score: float,
    config: RiskEngineConfig | None = None,
) -> RiskLevel:
    """Map overall score to risk level using effective thresholds.

    Args:
        score: The overall risk score.
        config: Optional runtime config overrides. When None, uses defaults.
    """
    thresholds = get_effective_risk_level_thresholds(config)
    for threshold, level in thresholds:
        if score >= threshold:
            return level
    return RiskLevel.LOW


def _find_group(signal_type: RiskSignalType) -> str | None:
    """Find which correlation group a signal type belongs to."""
    for group_name, members in CORRELATION_GROUPS.items():
        if signal_type in members:
            return group_name
    return None

"""Risk Engine — deterministic, explainable risk assessment.

Evaluates signals from upstream engines and trust data to produce
a RiskResult with overall_score, risk_level, confidence, and
a full evidence chain.

No database. No API calls. No LLM. No payment execution.
Does NOT make ALLOW/REVIEW/BLOCK decisions.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import structlog

from app.services.risk_engine.aggregator import (
    apply_correlation_groups,
    apply_dominant_boost,
    compute_confidence,
    compute_weighted_score,
    score_to_level,
)
from app.services.risk_engine.config import RiskEngineConfig
from app.services.risk_engine.constants import (
    EVALUATOR_VERSION,
    FEATURE_VERSION,
    RISK_MODEL_VERSION,
)
from app.services.risk_engine.models import (
    ComponentScores,
    RiskContext,
    RiskEvidence,
    RiskLevel,
    RiskResult,
    RiskSignalType,
)
from app.services.risk_engine.signals import (
    extract_agent_behavior_signal,
    extract_agent_trust_signal,
    extract_amount_anomaly_signal,
    extract_currency_mismatch_signal,
    extract_data_quality_signal,
    extract_geographic_anomaly_signal,
    extract_intent_drift_signal,
    extract_merchant_trust_signal,
    extract_policy_interaction_signal,
    extract_velocity_signal,
)

logger = structlog.get_logger()

# Ordered list of signal extractors — deterministic evaluation order
# Sprint 8: AGENT_TRUST and AGENT_BEHAVIOR are mutually exclusive —
# each extractor returns None when the other is active.
_SIGNAL_EXTRACTORS = [
    extract_intent_drift_signal,
    extract_amount_anomaly_signal,
    extract_agent_behavior_signal,  # Returns None when reputation unavailable
    extract_agent_trust_signal,     # Returns None when reputation available
    extract_merchant_trust_signal,
    extract_policy_interaction_signal,
    extract_velocity_signal,
    extract_currency_mismatch_signal,
    extract_geographic_anomaly_signal,
    extract_data_quality_signal,  # Last — never contributes to score
]


class RiskEngine:
    """Deterministic risk engine. No I/O, no DB, no LLM.

    Usage:
        engine = RiskEngine()
        result = engine.evaluate(context)
    """

    def evaluate(
        self,
        context: RiskContext,
        config: RiskEngineConfig | None = None,
    ) -> RiskResult:
        """Evaluate all risk signals and produce a deterministic RiskResult.

        Args:
            context: Pre-built RiskContext with all available signals.
            config: Optional runtime calibration config. When None, the
                exact existing Risk Engine defaults are used (backward
                compatible with Sprint 7–16 behavior).

        Returns:
            RiskResult with score, level, confidence, signals, and explanation.
        """
        start_time = time.monotonic()
        evaluation_id = str(uuid.uuid4())[:8]
        now = datetime.now(UTC)

        log = logger.bind(
            evaluation_id=evaluation_id,
            intent_id=context.intent_id,
            user_id=context.user_id,
            agent_id=context.agent_id,
        )

        # Step 1: Extract all signals
        raw_signals: list[RiskEvidence] = []
        for extractor in _SIGNAL_EXTRACTORS:
            signal = extractor(context)
            if signal is not None:
                raw_signals.append(signal)

        # Step 2: Apply correlation groups
        correlated_signals = apply_correlation_groups(raw_signals)

        # Step 3: Compute weighted score (uses config if provided)
        weighted_score = compute_weighted_score(correlated_signals, config)

        # Step 4: Apply dominant signal boost
        overall_score = apply_dominant_boost(weighted_score, correlated_signals)
        overall_score = round(max(0.0, min(1.0, overall_score)), 4)

        # Step 5: Compute confidence (uses config if provided)
        confidence = compute_confidence(context, correlated_signals, config)

        # Step 6: Map to risk level (uses config if provided)
        risk_level = score_to_level(overall_score, config)

        # Step 7: Build component scores
        component_scores = _build_component_scores(correlated_signals)

        # Step 8: Sort signals by contribution descending
        sorted_signals = sorted(
            correlated_signals,
            key=lambda s: s.risk_contribution,
            reverse=True,
        )

        # Step 9: Build summary
        summary = _build_summary(risk_level, overall_score, sorted_signals)

        latency_ms = int((time.monotonic() - start_time) * 1000)

        log.info(
            "risk_evaluation_completed",
            risk_level=risk_level.value,
            risk_score=overall_score,
            confidence=confidence,
            signal_count=len(sorted_signals),
            model_version=RISK_MODEL_VERSION,
            latency_ms=latency_ms,
        )

        if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            log.warning(
                f"risk_{risk_level.value}",
                risk_score=overall_score,
                confidence=confidence,
            )

        # Calibration metadata
        cal_active = config.calibration_active if config else False
        cal_version = config.calibration_version_id if config else ""
        cal_status = (
            "active" if cal_active
            else "default"
        )

        return RiskResult(
            overall_score=overall_score,
            risk_level=risk_level,
            confidence=confidence,
            component_scores=component_scores,
            signals=sorted_signals,
            signal_count=len(sorted_signals),
            summary=summary,
            evaluation_id=evaluation_id,
            risk_model_version=RISK_MODEL_VERSION,
            evaluator_version=EVALUATOR_VERSION,
            feature_version=FEATURE_VERSION,
            evaluated_at=now.isoformat(),
            calibration_active=cal_active,
            calibration_version_id=cal_version,
            calibration_validation_status=cal_status,
        )


def _build_component_scores(signals: list[RiskEvidence]) -> ComponentScores:
    """Map signals to component scores for the Decision Engine."""
    scores: dict[str, float | None] = {}
    for signal in signals:
        key = _signal_to_component_key(signal.signal_type)
        if key:
            scores[key] = signal.risk_contribution

    return ComponentScores(
        intent_match=scores.get("intent_match"),
        agent_trust=scores.get("agent_trust"),
        merchant_risk=scores.get("merchant_risk"),
        policy_risk=scores.get("policy_risk"),
        velocity_risk=scores.get("velocity_risk"),
        amount_anomaly=scores.get("amount_anomaly"),
        data_quality=scores.get("data_quality"),
    )


def _signal_to_component_key(signal_type: RiskSignalType) -> str | None:
    """Map signal type to component score key."""
    mapping = {
        RiskSignalType.INTENT_DRIFT: "intent_match",
        RiskSignalType.AGENT_TRUST: "agent_trust",
        RiskSignalType.AGENT_BEHAVIOR: "agent_trust",  # Maps to same component
        RiskSignalType.MERCHANT_TRUST: "merchant_risk",
        RiskSignalType.POLICY_INTERACTION: "policy_risk",
        RiskSignalType.VELOCITY: "velocity_risk",
        RiskSignalType.AMOUNT_ANOMALY: "amount_anomaly",
        RiskSignalType.DATA_QUALITY: "data_quality",
    }
    return mapping.get(signal_type)


def _build_summary(
    risk_level: RiskLevel,
    score: float,
    signals: list[RiskEvidence],
) -> str:
    """Build human-readable summary of the risk assessment."""
    # Find top contributing signals
    top_signals = [s for s in signals if s.risk_contribution > 0][:3]

    if not top_signals:
        return (
            f"Low risk ({score:.2f}). "
            "No significant risk indicators detected."
        )

    top_descriptions = [s.what for s in top_signals]
    return (
        f"{risk_level.value.title()} risk ({score:.2f}) "
        f"driven by: {'; '.join(top_descriptions)}"
    )

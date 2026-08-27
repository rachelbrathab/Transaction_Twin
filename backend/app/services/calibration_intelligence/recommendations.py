"""Calibration Intelligence — recommendation generator.

Generates advisory CalibrationRecommendation objects from metrics.
Deterministic — same metrics produce same recommendations.

GENERATED recommendations MUST NOT affect runtime behavior.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.services.calibration_intelligence.constants import (
    EXISTING_RISK_LEVEL_THRESHOLDS,
    FN_RATE_THRESHOLD_FOR_REVIEW,
    FP_RATE_THRESHOLD_FOR_REVIEW,
    MIN_SAMPLES_FPR_FNR,
    OVER_RISKING_THRESHOLD,
    POLICY_LOW_EFFECTIVENESS,
    REPUTATION_MISMATCH_THRESHOLD,
    UNDER_RISKING_THRESHOLD,
)
from app.services.calibration_intelligence.models import (
    AgentEffectiveness,
    CalibrationRecommendation,
    CalibrationVersion,
    DataSufficiencyLevel,
    MetricResult,
    PolicyEffectiveness,
    RecommendationStatus,
    RecommendationType,
    RiskOutcomeCrossTab,
)


def generate_recommendations(
    metrics: list[MetricResult],
    risk_cross_tab: list[RiskOutcomeCrossTab],
    policy_effectiveness: list[PolicyEffectiveness],
    agent_effectiveness: list[AgentEffectiveness],
    calibration_version: str,
    window_days: int = 30,
    total_samples: int = 0,
    eligible_samples: int = 0,
) -> tuple[list[CalibrationRecommendation], CalibrationVersion]:
    """Generate advisory recommendations from metrics.

    Returns:
        Tuple of (recommendations, version) — both deterministically
        generated from the input metrics.
    """
    now = datetime.now(UTC).isoformat()
    recommendations: list[CalibrationRecommendation] = []

    # ── Risk calibration recommendations ───────────────────────
    recommendations.extend(_risk_recommendations(
        risk_cross_tab, calibration_version, now,
    ))

    # ── Policy recommendations ─────────────────────────────────
    recommendations.extend(_policy_recommendations(
        policy_effectiveness, calibration_version, now,
    ))

    # ── Agent/reputation recommendations ───────────────────────
    recommendations.extend(_agent_recommendations(
        agent_effectiveness, calibration_version, now,
    ))

    # ── FPR/FNR summary recommendation ─────────────────────────
    fpr_metric = next(
        (m for m in metrics if m.metric_name == "false_positive_rate"),
        None,
    )
    fnr_metric = next(
        (m for m in metrics if m.metric_name == "false_negative_rate"),
        None,
    )

    if fpr_metric and fpr_metric.value is not None:
        if fpr_metric.value > FP_RATE_THRESHOLD_FOR_REVIEW:
            recommendations.append(CalibrationRecommendation(
                recommendation_id=_stable_id(
                    f"summary-fpr-{calibration_version}",
                ),
                recommendation_type=RecommendationType.SUMMARY,
                engine="risk_engine",
                parameter="overall_fpr",
                current_value=fpr_metric.value,
                proposed_value=None,
                evidence=fpr_metric.evidence,
                sample_count=fpr_metric.sample_count,
                data_sufficiency=fpr_metric.data_sufficiency,
                rationale=(
                    f"Overall false-positive rate is {fpr_metric.value:.1%}, "
                    f"above {FP_RATE_THRESHOLD_FOR_REVIEW:.0%} threshold. "
                    f"BLOCK decisions may be over-triggering."
                ),
                severity="warning",
                generated_at=now,
                calibration_version=calibration_version,
            ))

    if fnr_metric and fnr_metric.value is not None:
        if fnr_metric.value > FN_RATE_THRESHOLD_FOR_REVIEW:
            recommendations.append(CalibrationRecommendation(
                recommendation_id=_stable_id(
                    f"summary-fnr-{calibration_version}",
                ),
                recommendation_type=RecommendationType.SUMMARY,
                engine="risk_engine",
                parameter="overall_fnr",
                current_value=fnr_metric.value,
                proposed_value=None,
                evidence=fnr_metric.evidence,
                sample_count=fnr_metric.sample_count,
                data_sufficiency=fnr_metric.data_sufficiency,
                rationale=(
                    f"Overall false-negative rate is {fnr_metric.value:.1%}, "
                    f"above {FN_RATE_THRESHOLD_FOR_REVIEW:.0%} threshold. "
                    f"ALLOW decisions may be under-protective."
                ),
                severity="warning",
                generated_at=now,
                calibration_version=calibration_version,
            ))

    # ── Build version ──────────────────────────────────────────
    excluded = total_samples - eligible_samples
    version = CalibrationVersion(
        version_id=calibration_version,
        generated_at=now,
        source_window_days=window_days,
        total_samples=total_samples,
        eligible_samples=eligible_samples,
        excluded_samples=excluded,
        recommendation_count=len(recommendations),
        status=RecommendationStatus.GENERATED,
    )

    return recommendations, version


# ── Internal generators ────────────────────────────────────────────


def _risk_recommendations(
    cross_tab: list[RiskOutcomeCrossTab],
    calibration_version: str,
    now: str,
) -> list[CalibrationRecommendation]:
    """Generate risk calibration recommendations from cross-tabulation."""
    recs: list[CalibrationRecommendation] = []

    if len(cross_tab) < 1:
        return recs

    # Per-level minimum rather than total minimum,
    # because each risk level needs sufficient evidence independently.
    min_per_level = 10

    # Check for over-risking: HIGH risk + many correct_als
    for ct in cross_tab:
        if ct.risk_level in ("high", "critical") and ct.total > 0:
            allow_rate = ct.correct_allow / ct.total
            if allow_rate > OVER_RISKING_THRESHOLD and ct.total >= min_per_level:
                recs.append(CalibrationRecommendation(
                    recommendation_id=_stable_id(
                        f"over-risk-{ct.risk_level}-{calibration_version}",
                    ),
                    recommendation_type=RecommendationType.THRESHOLD_REVIEW,
                    engine="risk_engine",
                    parameter="RISK_LEVEL_THRESHOLDS",
                    current_value=EXISTING_RISK_LEVEL_THRESHOLDS.get(
                        ct.risk_level
                    ),
                    proposed_range=(
                        EXISTING_RISK_LEVEL_THRESHOLDS.get(ct.risk_level, 0.0),
                        min(
                            1.0,
                            EXISTING_RISK_LEVEL_THRESHOLDS.get(
                                ct.risk_level, 0.0
                            ) + 0.15,
                        ),
                    ),
                    evidence={
                        "risk_level": ct.risk_level,
                        "correct_allow_rate": round(allow_rate, 4),
                        "total_samples": ct.total,
                    },
                    sample_count=ct.total,
                    data_sufficiency=DataSufficiencyLevel.MODERATE,
                    rationale=(
                        f"{ct.risk_level.upper()} risk level has "
                        f"{allow_rate:.0%} correct-ALLOW rate across "
                        f"{ct.total} samples — possible over-risking. "
                        f"Consider reviewing the threshold."
                    ),
                    severity="warning",
                    generated_at=now,
                    calibration_version=calibration_version,
                ))

        # Check for under-risking: LOW risk + many false negatives
        if ct.risk_level == "low" and ct.total > 0:
            fn_rate = ct.false_negative / ct.total
            if fn_rate > UNDER_RISKING_THRESHOLD and ct.total >= min_per_level:
                recs.append(CalibrationRecommendation(
                    recommendation_id=_stable_id(
                        f"under-risk-low-{calibration_version}",
                    ),
                    recommendation_type=RecommendationType.THRESHOLD_REVIEW,
                    engine="risk_engine",
                    parameter="RISK_LEVEL_THRESHOLDS",
                    current_value=EXISTING_RISK_LEVEL_THRESHOLDS.get("low"),
                    proposed_range=(0.0, 0.15),
                    evidence={
                        "risk_level": "low",
                        "false_negative_rate": round(fn_rate, 4),
                        "total_samples": ct.total,
                    },
                    sample_count=ct.total,
                    data_sufficiency=DataSufficiencyLevel.MODERATE,
                    rationale=(
                        f"LOW risk level has {fn_rate:.0%} false-negative "
                        f"rate across {ct.total} samples — possible "
                        f"under-risking. Consider reviewing the threshold."
                    ),
                    severity="warning",
                    generated_at=now,
                    calibration_version=calibration_version,
                ))

    return recs


def _policy_recommendations(
    policy_eff: list[PolicyEffectiveness],
    calibration_version: str,
    now: str,
) -> list[CalibrationRecommendation]:
    """Generate policy review recommendations."""
    recs: list[CalibrationRecommendation] = []

    for p in policy_eff:
        # High FP rate
        if (
            p.fp_rate is not None
            and p.fp_rate > FP_RATE_THRESHOLD_FOR_REVIEW
            and p.total_evaluations >= MIN_SAMPLES_FPR_FNR
        ):
            recs.append(CalibrationRecommendation(
                recommendation_id=_stable_id(
                    f"policy-fp-{p.policy_id}-{calibration_version}",
                ),
                recommendation_type=RecommendationType.POLICY_REVIEW,
                engine="policy_engine",
                parameter=p.policy_id,
                current_value={"fp_rate": p.fp_rate},
                proposed_value=None,
                evidence={
                    "policy_id": p.policy_id,
                    "policy_name": p.policy_name,
                    "fp_rate": p.fp_rate,
                    "false_positive_count": p.false_positive_count,
                    "total_evaluations": p.total_evaluations,
                },
                sample_count=p.total_evaluations,
                data_sufficiency=p.data_sufficiency,
                rationale=(
                    f"Policy '{p.policy_name}' has {p.fp_rate:.0%} "
                    f"false-positive rate — may be over-triggering."
                ),
                severity="warning",
                generated_at=now,
                calibration_version=calibration_version,
            ))

        # Low effectiveness
        if (
            p.effectiveness_score is not None
            and p.effectiveness_score < POLICY_LOW_EFFECTIVENESS
            and p.total_evaluations >= MIN_SAMPLES_FPR_FNR
        ):
            recs.append(CalibrationRecommendation(
                recommendation_id=_stable_id(
                    f"policy-eff-{p.policy_id}-{calibration_version}",
                ),
                recommendation_type=RecommendationType.POLICY_REVIEW,
                engine="policy_engine",
                parameter=p.policy_id,
                current_value={"effectiveness": p.effectiveness_score},
                proposed_value=None,
                evidence={
                    "policy_id": p.policy_id,
                    "policy_name": p.policy_name,
                    "effectiveness": p.effectiveness_score,
                    "total_evaluations": p.total_evaluations,
                },
                sample_count=p.total_evaluations,
                data_sufficiency=p.data_sufficiency,
                rationale=(
                    f"Policy '{p.policy_name}' has "
                    f"{p.effectiveness_score:.0%} effectiveness — "
                    f"may need review."
                ),
                severity="info",
                generated_at=now,
                calibration_version=calibration_version,
            ))

    return recs


def _agent_recommendations(
    agent_eff: list[AgentEffectiveness],
    calibration_version: str,
    now: str,
) -> list[CalibrationRecommendation]:
    """Generate reputation/agent calibration recommendations."""
    recs: list[CalibrationRecommendation] = []

    for a in agent_eff:
        if a.total_verified < REPUTATION_MISMATCH_THRESHOLD:
            continue

        # High false-negative rate → agent reputation may be too high
        if (
            a.false_negative_count >= REPUTATION_MISMATCH_THRESHOLD
            and a.false_negative_count > a.correct_count
        ):
            recs.append(CalibrationRecommendation(
                recommendation_id=_stable_id(
                    f"rep-fn-{a.agent_id}-{calibration_version}",
                ),
                recommendation_type=RecommendationType.REPUTATION_REVIEW,
                engine="reputation_engine",
                parameter=a.agent_id,
                current_value={
                    "reputation_level": a.reputation_level,
                    "reputation_score": a.reputation_score,
                },
                proposed_value=None,
                evidence={
                    "agent_id": a.agent_id,
                    "agent_name": a.agent_name,
                    "false_negative_count": a.false_negative_count,
                    "correct_count": a.correct_count,
                    "total_verified": a.total_verified,
                },
                sample_count=a.total_verified,
                data_sufficiency=a.data_sufficiency,
                rationale=(
                    f"Agent '{a.agent_name or a.agent_id}' has "
                    f"{a.false_negative_count} false-negatives vs "
                    f"{a.correct_count} correct — reputation may "
                    f"need recalibration."
                ),
                severity="warning",
                generated_at=now,
                calibration_version=calibration_version,
            ))

        # High false-positive rate → agent may be over-blocked
        if (
            a.false_positive_count >= REPUTATION_MISMATCH_THRESHOLD
            and a.false_positive_count > a.correct_count
        ):
            recs.append(CalibrationRecommendation(
                recommendation_id=_stable_id(
                    f"rep-fp-{a.agent_id}-{calibration_version}",
                ),
                recommendation_type=RecommendationType.REPUTATION_REVIEW,
                engine="reputation_engine",
                parameter=a.agent_id,
                current_value={
                    "reputation_level": a.reputation_level,
                    "reputation_score": a.reputation_score,
                },
                proposed_value=None,
                evidence={
                    "agent_id": a.agent_id,
                    "agent_name": a.agent_name,
                    "false_positive_count": a.false_positive_count,
                    "correct_count": a.correct_count,
                    "total_verified": a.total_verified,
                },
                sample_count=a.total_verified,
                data_sufficiency=a.data_sufficiency,
                rationale=(
                    f"Agent '{a.agent_name or a.agent_id}' has "
                    f"{a.false_positive_count} false-positives vs "
                    f"{a.correct_count} correct — may be over-blocked."
                ),
                severity="info",
                generated_at=now,
                calibration_version=calibration_version,
            ))

    return recs


def _stable_id(seed: str) -> str:
    """Generate a deterministic ID from a seed string."""
    return hashlib.sha256(seed.encode()).hexdigest()[:16]

"""Calibration Intelligence — deterministic metrics.

Computes calibration metrics from a CalibrationDataset.
Pure functions — no database, no I/O, no side effects.
"""

from __future__ import annotations

from app.services.calibration_intelligence.constants import (
    MIN_SAMPLES_AGENT_CALIBRATION,
    MIN_SAMPLES_DECISION_ACCURACY,
    MIN_SAMPLES_FPR_FNR,
    MIN_SAMPLES_POLICY_EFFECTIVENESS,
    MIN_SAMPLES_RISK_CALIBRATION,
    SUFFICIENCY_THRESHOLDS,
)
from app.services.calibration_intelligence.models import (
    AgentEffectiveness,
    CalibrationDataset,
    CalibrationSample,
    DataSufficiencyLevel,
    MetricResult,
    PolicyEffectiveness,
    RiskOutcomeCrossTab,
)


def compute_data_sufficiency(count: int) -> DataSufficiencyLevel:
    """Determine data sufficiency level from sample count."""
    for threshold, level_str in SUFFICIENCY_THRESHOLDS:
        if count >= threshold:
            return DataSufficiencyLevel(level_str)
    return DataSufficiencyLevel.INSUFFICIENT


def compute_decision_accuracy(
    dataset: CalibrationDataset,
) -> MetricResult:
    """Compute decision accuracy proxy from eligible samples."""
    eligible = [s for s in dataset.samples if s.sample_eligible]
    if not eligible:
        return MetricResult(
            metric_name="decision_accuracy",
            value=None,
            sample_count=0,
            data_sufficiency=DataSufficiencyLevel.INSUFFICIENT,
            explanation="No eligible samples",
        )

    correct = sum(
        1 for s in eligible
        if s.feedback_type in ("correct_allow", "correct_block", "correct_review")
    )
    total = len(eligible)
    value = correct / total if total > 0 else 0.0
    sufficiency = compute_data_sufficiency(total)

    return MetricResult(
        metric_name="decision_accuracy",
        value=round(value, 4),
        sample_count=total,
        data_sufficiency=sufficiency,
        confidence=min(1.0, total / MIN_SAMPLES_DECISION_ACCURACY),
        evidence={
            "correct_count": correct,
            "total_count": total,
            "feedback_distribution": _feedback_distribution(eligible),
        },
        explanation=(
            f"Decision accuracy: {value:.1%} across {total} verified samples"
        ),
    )


def compute_false_positive_rate(
    dataset: CalibrationDataset,
) -> MetricResult:
    """Compute false-positive rate (BLOCK decisions that were safe)."""
    eligible = [s for s in dataset.samples if s.sample_eligible]
    block_samples = [
        s for s in eligible if s.original_decision == "block"
    ]
    total_block = len(block_samples)
    fp_count = sum(
        1 for s in block_samples
        if s.feedback_type == "possible_false_positive"
    )
    correct_block = sum(
        1 for s in block_samples
        if s.feedback_type == "correct_block"
    )

    if total_block < MIN_SAMPLES_FPR_FNR:
        return MetricResult(
            metric_name="false_positive_rate",
            value=None,
            sample_count=total_block,
            data_sufficiency=compute_data_sufficiency(total_block),
            explanation=(
                f"Insufficient BLOCK samples ({total_block}) "
                f"for FPR computation (need {MIN_SAMPLES_FPR_FNR})"
            ),
        )

    denominator = fp_count + correct_block
    value = fp_count / denominator if denominator > 0 else 0.0

    return MetricResult(
        metric_name="false_positive_rate",
        value=round(value, 4),
        sample_count=total_block,
        data_sufficiency=compute_data_sufficiency(total_block),
        confidence=min(1.0, total_block / MIN_SAMPLES_FPR_FNR),
        evidence={
            "false_positive_count": fp_count,
            "correct_block_count": correct_block,
            "total_block_count": total_block,
        },
        explanation=(
            f"False-positive rate: {value:.1%} across {total_block} "
            f"BLOCK decisions"
        ),
    )


def compute_false_negative_rate(
    dataset: CalibrationDataset,
) -> MetricResult:
    """Compute false-negative rate (ALLOW decisions that were fraudulent)."""
    eligible = [s for s in dataset.samples if s.sample_eligible]
    allow_samples = [
        s for s in eligible if s.original_decision == "allow"
    ]
    total_allow = len(allow_samples)
    fn_count = sum(
        1 for s in allow_samples
        if s.feedback_type == "possible_false_negative"
    )
    correct_allow = sum(
        1 for s in allow_samples
        if s.feedback_type == "correct_allow"
    )

    if total_allow < MIN_SAMPLES_FPR_FNR:
        return MetricResult(
            metric_name="false_negative_rate",
            value=None,
            sample_count=total_allow,
            data_sufficiency=compute_data_sufficiency(total_allow),
            explanation=(
                f"Insufficient ALLOW samples ({total_allow}) "
                f"for FNR computation (need {MIN_SAMPLES_FPR_FNR})"
            ),
        )

    denominator = fn_count + correct_allow
    value = fn_count / denominator if denominator > 0 else 0.0

    return MetricResult(
        metric_name="false_negative_rate",
        value=round(value, 4),
        sample_count=total_allow,
        data_sufficiency=compute_data_sufficiency(total_allow),
        confidence=min(1.0, total_allow / MIN_SAMPLES_FPR_FNR),
        evidence={
            "false_negative_count": fn_count,
            "correct_allow_count": correct_allow,
            "total_allow_count": total_allow,
        },
        explanation=(
            f"False-negative rate: {value:.1%} across {total_allow} "
            f"ALLOW decisions"
        ),
    )


def compute_risk_cross_tab(
    dataset: CalibrationDataset,
) -> list[RiskOutcomeCrossTab]:
    """Cross-tabulate risk levels against verified outcomes."""
    eligible = [
        s for s in dataset.samples
        if s.sample_eligible and s.risk_available and s.risk_level
    ]

    if len(eligible) < MIN_SAMPLES_RISK_CALIBRATION:
        return []

    # Group by risk level
    by_level: dict[str, list[CalibrationSample]] = {}
    for s in eligible:
        level = s.risk_level or "unknown"
        by_level.setdefault(level, []).append(s)

    results: list[RiskOutcomeCrossTab] = []
    for level in ("low", "medium", "high", "critical"):
        samples = by_level.get(level, [])
        if not samples:
            continue

        results.append(RiskOutcomeCrossTab(
            risk_level=level,
            correct_allow=sum(
                1 for s in samples if s.feedback_type == "correct_allow"
            ),
            correct_block=sum(
                1 for s in samples if s.feedback_type == "correct_block"
            ),
            correct_review=sum(
                1 for s in samples if s.feedback_type == "correct_review"
            ),
            false_positive=sum(
                1 for s in samples
                if s.feedback_type == "possible_false_positive"
            ),
            false_negative=sum(
                1 for s in samples
                if s.feedback_type == "possible_false_negative"
            ),
            total=len(samples),
        ))

    return results


def compute_policy_effectiveness(
    dataset: CalibrationDataset,
    policy_names: dict[str, str] | None = None,
) -> list[PolicyEffectiveness]:
    """Compute per-policy effectiveness from verified outcomes."""
    eligible = [s for s in dataset.samples if s.sample_eligible]
    policy_names = policy_names or {}

    # Group by policy
    by_policy: dict[str, list[CalibrationSample]] = {}
    for s in eligible:
        if s.policy_id:
            by_policy.setdefault(s.policy_id, []).append(s)

    results: list[PolicyEffectiveness] = []
    for policy_id, samples in by_policy.items():
        total = len(samples)
        if total < MIN_SAMPLES_POLICY_EFFECTIVENESS:
            continue

        correct_block = sum(
            1 for s in samples if s.feedback_type == "correct_block"
        )
        fp = sum(
            1 for s in samples
            if s.feedback_type == "possible_false_positive"
        )
        fn = sum(
            1 for s in samples
            if s.feedback_type == "possible_false_negative"
        )
        correct_allow = sum(
            1 for s in samples if s.feedback_type == "correct_allow"
        )

        correct = correct_block + correct_allow
        effectiveness = correct / total if total > 0 else None

        # FP rate for this policy
        fp_denom = fp + correct_block
        fp_rate = fp / fp_denom if fp_denom > 0 else None

        # FN rate for this policy
        fn_denom = fn + correct_allow
        fn_rate = fn / fn_denom if fn_denom > 0 else None

        results.append(PolicyEffectiveness(
            policy_id=policy_id,
            policy_name=policy_names.get(policy_id, policy_id),
            total_evaluations=total,
            correct_block_count=correct_block,
            false_positive_count=fp,
            false_negative_count=fn,
            correct_allow_count=correct_allow,
            trigger_rate=samples[0].policy_triggered_count / total
            if samples[0].policy_triggered_count > 0
            else 0.0,
            fp_rate=round(fp_rate, 4) if fp_rate is not None else None,
            fn_rate=round(fn_rate, 4) if fn_rate is not None else None,
            effectiveness_score=round(effectiveness, 4)
            if effectiveness is not None
            else None,
            data_sufficiency=compute_data_sufficiency(total),
        ))

    return results


def compute_agent_effectiveness(
    dataset: CalibrationDataset,
    agent_names: dict[str, str] | None = None,
) -> list[AgentEffectiveness]:
    """Compute per-agent effectiveness from verified outcomes."""
    eligible = [s for s in dataset.samples if s.sample_eligible]
    agent_names = agent_names or {}

    by_agent: dict[str, list[CalibrationSample]] = {}
    for s in eligible:
        if s.agent_id:
            by_agent.setdefault(s.agent_id, []).append(s)

    results: list[AgentEffectiveness] = []
    for agent_id, samples in by_agent.items():
        total = len(samples)
        if total < MIN_SAMPLES_AGENT_CALIBRATION:
            continue

        correct = sum(
            1 for s in samples
            if s.feedback_type in (
                "correct_allow", "correct_block", "correct_review",
            )
        )
        fp = sum(
            1 for s in samples
            if s.feedback_type == "possible_false_positive"
        )
        fn = sum(
            1 for s in samples
            if s.feedback_type == "possible_false_negative"
        )
        correct_rate = correct / total if total > 0 else None

        results.append(AgentEffectiveness(
            agent_id=agent_id,
            agent_name=agent_names.get(agent_id),
            total_verified=total,
            correct_count=correct,
            false_positive_count=fp,
            false_negative_count=fn,
            correct_rate=round(correct_rate, 4)
            if correct_rate is not None
            else None,
            data_sufficiency=compute_data_sufficiency(total),
        ))

    return results


def compute_all_metrics(
    dataset: CalibrationDataset,
) -> list[MetricResult]:
    """Compute all calibration metrics from a dataset."""
    return [
        compute_decision_accuracy(dataset),
        compute_false_positive_rate(dataset),
        compute_false_negative_rate(dataset),
    ]


# ── Helpers ────────────────────────────────────────────────────────


def _feedback_distribution(
    samples: list[CalibrationSample],
) -> dict[str, int]:
    """Count feedback types in a sample list."""
    dist: dict[str, int] = {}
    for s in samples:
        dist[s.feedback_type] = dist.get(s.feedback_type, 0) + 1
    return dist

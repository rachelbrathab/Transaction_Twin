"""Drift detection for calibration.

Compares system behavior between baseline and current periods.
Pure functions — no I/O, no database, no side effects.
"""

from __future__ import annotations

from app.services.calibration_engine.constants import (
    DRIFT_ALLOW_RATE_DECREASE,
    DRIFT_BLOCK_RATE_RATIO,
    DRIFT_MIN_BASELINE,
    DRIFT_MIN_CURRENT,
    DRIFT_POLICY_TRIGGER_RATIO,
    DRIFT_REVIEW_RATE_RATIO,
)
from app.services.calibration_engine.models import (
    CalibrationContext,
    CalibrationFinding,
    DataSufficiencyLevel,
    DriftDetection,
    FindingSeverity,
    FindingType,
)


def detect_drift(
    baseline_ctx: CalibrationContext,
    current_ctx: CalibrationContext,
) -> list[DriftDetection]:
    """Compare baseline and current period distributions for drift."""
    detections: list[DriftDetection] = []

    baseline_total = len(baseline_ctx.decisions)
    current_total = len(current_ctx.decisions)

    # Need minimum data in both periods
    if baseline_total < DRIFT_MIN_BASELINE or current_total < DRIFT_MIN_CURRENT:
        return detections

    # ── Decision rate drift ────────────────────────────────────
    for metric_name, getter, ratio_threshold in [
        ("block_rate", _block_rate, DRIFT_BLOCK_RATE_RATIO),
        ("review_rate", _review_rate, DRIFT_REVIEW_RATE_RATIO),
    ]:
        b_val = getter(baseline_ctx)
        c_val = getter(current_ctx)
        ratio = c_val / b_val if b_val > 0 else float("inf")

        is_drifting = (
            b_val > 0
            and ratio > ratio_threshold
        )

        explanation = ""
        if is_drifting:
            explanation = (
                f"{metric_name} increased from {b_val:.1%} to {c_val:.1%} "
                f"({ratio:.1f}× baseline)"
            )
        elif b_val == 0 and c_val > 0:
            is_drifting = True
            explanation = (
                f"{metric_name} appeared at {c_val:.1%} "
                f"(was 0% in baseline)"
            )
        else:
            explanation = (
                f"{metric_name} stable at {c_val:.1%} "
                f"(baseline: {b_val:.1%})"
            )

        detections.append(DriftDetection(
            metric_name=metric_name,
            baseline_value=round(b_val, 4),
            current_value=round(c_val, 4),
            change_ratio=round(ratio, 4) if b_val > 0 else 0.0,
            is_drifting=is_drifting,
            explanation=explanation,
            baseline_sample_count=baseline_total,
            current_sample_count=current_total,
        ))

    # ── Allow rate decrease ────────────────────────────────────
    b_allow = _allow_rate(baseline_ctx)
    c_allow = _allow_rate(current_ctx)
    if b_allow > 0:
        decrease = (b_allow - c_allow) / b_allow
    else:
        decrease = 0.0

    is_drifting_allow = decrease > DRIFT_ALLOW_RATE_DECREASE
    if is_drifting_allow:
        allow_explanation = (
            f"allow_rate decreased from {b_allow:.1%} to {c_allow:.1%} "
            f"({decrease:.0%} decrease)"
        )
    else:
        allow_explanation = (
            f"allow_rate stable at {c_allow:.1%} (baseline: {b_allow:.1%})"
        )

    detections.append(DriftDetection(
        metric_name="allow_rate",
        baseline_value=round(b_allow, 4),
        current_value=round(c_allow, 4),
        change_ratio=round(decrease, 4),
        is_drifting=is_drifting_allow,
        explanation=allow_explanation,
        baseline_sample_count=baseline_total,
        current_sample_count=current_total,
    ))

    # ── Policy trigger drift ───────────────────────────────────
    b_trigger_rate = _avg_policy_trigger_rate(baseline_ctx)
    c_trigger_rate = _avg_policy_trigger_rate(current_ctx)
    if b_trigger_rate > 0:
        p_ratio = c_trigger_rate / b_trigger_rate
    else:
        p_ratio = float("inf") if c_trigger_rate > 0 else 1.0

    is_drifting_policy = (
        b_trigger_rate > 0 and p_ratio > DRIFT_POLICY_TRIGGER_RATIO
    )
    if is_drifting_policy:
        policy_explanation = (
            f"policy_trigger_rate increased from {b_trigger_rate:.1%} "
            f"to {c_trigger_rate:.1%} ({p_ratio:.1f}× baseline)"
        )
    else:
        policy_explanation = (
            f"policy_trigger_rate stable at {c_trigger_rate:.1%} "
            f"(baseline: {b_trigger_rate:.1%})"
        )

    detections.append(DriftDetection(
        metric_name="policy_trigger_rate",
        baseline_value=round(b_trigger_rate, 4),
        current_value=round(c_trigger_rate, 4),
        change_ratio=round(p_ratio, 4) if b_trigger_rate > 0 else 0.0,
        is_drifting=is_drifting_policy,
        explanation=policy_explanation,
        baseline_sample_count=baseline_total,
        current_sample_count=current_total,
    ))

    return detections


def generate_drift_findings(
    detections: list[DriftDetection],
) -> list[CalibrationFinding]:
    """Generate explanatory findings from drift detections."""
    findings = []
    for det in detections:
        if det.is_drifting:
            findings.append(CalibrationFinding(
                finding_type=FindingType.DRIFT_DETECTED,
                severity=FindingSeverity.WARNING,
                title=f"Drift detected: {det.metric_name}",
                explanation=det.explanation,
                evidence={
                    "metric": det.metric_name,
                    "baseline": det.baseline_value,
                    "current": det.current_value,
                    "ratio": det.change_ratio,
                },
                sample_count=det.baseline_sample_count + det.current_sample_count,
                data_sufficiency=DataSufficiencyLevel.MODERATE
                if (det.baseline_sample_count >= 30
                    and det.current_sample_count >= 30)
                else DataSufficiencyLevel.LOW,
            ))
    return findings


def _block_rate(ctx: CalibrationContext) -> float:
    total = len(ctx.decisions)
    if total == 0:
        return 0.0
    blocks = sum(1 for d in ctx.decisions if d.decision == "block")
    return blocks / total


def _review_rate(ctx: CalibrationContext) -> float:
    total = len(ctx.decisions)
    if total == 0:
        return 0.0
    reviews = sum(1 for d in ctx.decisions if d.decision == "review")
    return reviews / total


def _allow_rate(ctx: CalibrationContext) -> float:
    total = len(ctx.decisions)
    if total == 0:
        return 0.0
    allows = sum(1 for d in ctx.decisions if d.decision == "allow")
    return allows / total


def _avg_policy_trigger_rate(ctx: CalibrationContext) -> float:
    total = len(ctx.decisions)
    if total == 0:
        return 0.0
    total_triggers = sum(d.policy_triggered_count for d in ctx.decisions)
    return total_triggers / total

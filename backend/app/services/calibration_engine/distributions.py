"""Distribution analysis for calibration.

Pure functions that compute decision, risk, and signal distributions.
No I/O, no database, no side effects.
"""

from __future__ import annotations

from app.services.calibration_engine.constants import SIGNAL_SOURCES
from app.services.calibration_engine.models import (
    CalibrationContext,
    DecisionDistribution,
    RiskLevelDistribution,
    SignalContribution,
    SignalContributionDistribution,
)


def compute_decision_distribution(ctx: CalibrationContext) -> DecisionDistribution:
    """Compute the distribution of decision outcomes."""
    total = len(ctx.decisions)
    if total == 0:
        return DecisionDistribution(
            total=0,
            allow_count=0,
            review_count=0,
            block_count=0,
            allow_rate=0.0,
            review_rate=0.0,
            block_rate=0.0,
            sample_count=0,
        )

    allow = sum(1 for d in ctx.decisions if d.decision == "allow")
    review = sum(1 for d in ctx.decisions if d.decision == "review")
    block = sum(1 for d in ctx.decisions if d.decision == "block")

    return DecisionDistribution(
        total=total,
        allow_count=allow,
        review_count=review,
        block_count=block,
        allow_rate=round(allow / total, 4),
        review_rate=round(review / total, 4),
        block_rate=round(block / total, 4),
        sample_count=total,
    )


def compute_risk_distribution(ctx: CalibrationContext) -> RiskLevelDistribution:
    """Compute risk level distribution from decision explanations.

    Only uses risk data that is genuinely available in explanation JSONB.
    """
    total_with_risk = 0
    low = 0
    medium = 0
    high = 0
    critical = 0
    unavailable = 0

    for d in ctx.decisions:
        risk_info = d.explanation.get("risk", {})
        if not risk_info.get("available", False):
            unavailable += 1
            continue

        total_with_risk += 1
        # Risk level is stored in risk_summary in the DecisionResult,
        # but not directly in explanation. We check signals for risk.
        risk_signal = _find_risk_signal(d)
        if risk_signal is None:
            continue

        level = risk_signal.get("severity", "")
        if level == "critical":
            critical += 1
        elif level == "high":
            high += 1
        elif level == "medium":
            medium += 1
        elif level == "low":
            low += 1

    return RiskLevelDistribution(
        total_with_risk=total_with_risk,
        low_count=low,
        medium_count=medium,
        high_count=high,
        critical_count=critical,
        risk_unavailable_count=unavailable,
    )


def compute_signal_distribution(
    ctx: CalibrationContext,
) -> SignalContributionDistribution:
    """Compute signal source contribution distribution."""
    total = len(ctx.decisions)
    source_stats: dict[str, dict[str, int]] = {
        src: {"appeared": 0, "positive": 0, "negative": 0,
              "unknown": 0, "violation": 0}
        for src in SIGNAL_SOURCES
    }

    for d in ctx.decisions:
        signals_by_source = d.explanation.get("signals_by_source", {})
        if not isinstance(signals_by_source, dict):
            continue

        for source, signal_list in signals_by_source.items():
            if source not in source_stats:
                continue
            if not isinstance(signal_list, list):
                continue

            source_stats[source]["appeared"] += 1

            for sig in signal_list:
                if not isinstance(sig, dict):
                    continue
                status = sig.get("status", "")
                if status == "positive":
                    source_stats[source]["positive"] += 1
                elif status in ("negative", "triggered"):
                    source_stats[source]["negative"] += 1
                elif status == "unknown":
                    source_stats[source]["unknown"] += 1
                elif status == "violation":
                    source_stats[source]["violation"] += 1

    signals = []
    for source in SIGNAL_SOURCES:
        stats = source_stats[source]
        appeared = stats["appeared"]
        signals.append(SignalContribution(
            source=source,
            appeared_count=appeared,
            positive_count=stats["positive"],
            negative_count=stats["negative"],
            unknown_count=stats["unknown"],
            violation_count=stats["violation"],
            contribution_rate=round(appeared / total, 4) if total > 0 else 0.0,
        ))

    return SignalContributionDistribution(
        signals=signals,
        total_decisions=total,
    )


def _find_risk_signal(decision: dict | None) -> dict | None:
    """Find the risk signal in a decision's explanation signals."""
    if decision is None:
        return None
    signals_by_source = decision.explanation.get("signals_by_source", {})
    if not isinstance(signals_by_source, dict):
        return None
    risk_signals = signals_by_source.get("risk", [])
    if not isinstance(risk_signals, list) or not risk_signals:
        return None
    return risk_signals[0] if isinstance(risk_signals[0], dict) else None

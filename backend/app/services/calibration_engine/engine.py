"""Calibration Engine — deterministic, explainable decision calibration.

Analyzes historical decisions to evaluate system behavior, detect drift,
and produce actionable findings. Read-only — never modifies policies,
thresholds, risk weights, or reputation.

No database. No API calls. No LLM. No external service calls.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import structlog

from app.services.calibration_engine.agent_analysis import (
    analyze_agents,
    identify_unstable_agents,
)
from app.services.calibration_engine.constants import (
    SUFFICIENCY_THRESHOLDS,
)
from app.services.calibration_engine.distributions import (
    compute_decision_distribution,
    compute_risk_distribution,
    compute_signal_distribution,
)
from app.services.calibration_engine.models import (
    CalibrationContext,
    CalibrationFinding,
    CalibrationResult,
    DataSufficiency,
    DataSufficiencyLevel,
    FindingSeverity,
    FindingType,
)
from app.services.calibration_engine.policy_analysis import (
    analyze_policies,
    get_high_trigger_policies,
)

logger = structlog.get_logger()


class CalibrationEngine:
    """Deterministic calibration engine. No I/O, no DB, no LLM.

    Usage:
        engine = CalibrationEngine()
        result = engine.evaluate(context)
    """

    def evaluate(self, context: CalibrationContext) -> CalibrationResult:
        """Evaluate calibration of the decision system.

        Args:
            context: Pre-built CalibrationContext with historical data.

        Returns:
            CalibrationResult with metrics, findings, and explanation.
        """
        start_time = time.monotonic()
        now = datetime.now(UTC)

        log = logger.bind(
            user_id=context.user_id,
            window_days=context.window_days,
            decision_count=len(context.decisions),
        )

        # Step 1: Data sufficiency
        data_suff = _compute_sufficiency(len(context.decisions))

        # Step 2: Decision distribution
        decision_dist = compute_decision_distribution(context)

        # Step 3: Risk distribution
        risk_dist = compute_risk_distribution(context)

        # Step 4: Signal distribution
        signal_dist = compute_signal_distribution(context)

        # Step 5: Policy analysis
        policy_summaries = analyze_policies(context)

        # Step 6: Agent analysis
        agent_summaries = analyze_agents(context)

        # Step 7: Drift detection (needs separate baseline context)
        drift_detections: list = []
        drift_findings: list[CalibrationFinding] = []

        # Step 8: Generate findings
        findings: list[CalibrationFinding] = []

        # System summary finding
        findings.append(CalibrationFinding(
            finding_type=FindingType.SYSTEM_SUMMARY,
            severity=FindingSeverity.INFO,
            title="System Calibration Summary",
            explanation=(
                f"Analyzed {len(context.decisions)} decisions over "
                f"{context.window_days} days. "
                f"ALLOW: {decision_dist.allow_rate:.1%}, "
                f"REVIEW: {decision_dist.review_rate:.1%}, "
                f"BLOCK: {decision_dist.block_rate:.1%}."
            ),
            evidence={
                "total_decisions": len(context.decisions),
                "allow_rate": decision_dist.allow_rate,
                "review_rate": decision_dist.review_rate,
                "block_rate": decision_dist.block_rate,
            },
            sample_count=len(context.decisions),
            data_sufficiency=data_suff.level,
        ))

        # High trigger rate policies
        high_trigger = get_high_trigger_policies(policy_summaries)
        for p in high_trigger:
            findings.append(CalibrationFinding(
                finding_type=FindingType.HIGH_TRIGGER_RATE,
                severity=FindingSeverity.WARNING,
                title=f"High trigger rate: {p.policy_name}",
                explanation=(
                    f"Policy '{p.policy_name}' triggered in "
                    f"{p.trigger_rate:.0%} of {p.evaluation_count} "
                    f"evaluations — may require review."
                ),
                evidence={
                    "policy_id": p.policy_id,
                    "trigger_rate": p.trigger_rate,
                    "trigger_count": p.trigger_count,
                    "evaluation_count": p.evaluation_count,
                },
                sample_count=p.evaluation_count,
                data_sufficiency=data_suff.level,
            ))

        # Unstable agents
        unstable = identify_unstable_agents(agent_summaries)
        for a in unstable:
            findings.append(CalibrationFinding(
                finding_type=FindingType.UNSTABLE_AGENT,
                severity=FindingSeverity.WARNING,
                title=f"Unstable agent: {a.agent_name or a.agent_id}",
                explanation=(
                    f"Agent '{a.agent_name or a.agent_id}' has "
                    f"{a.review_rate:.0%} REVIEW and "
                    f"{a.block_rate:.0%} BLOCK rate over "
                    f"{a.total_decisions} decisions."
                ),
                evidence={
                    "agent_id": a.agent_id,
                    "review_rate": a.review_rate,
                    "block_rate": a.block_rate,
                    "total_decisions": a.total_decisions,
                },
                sample_count=a.total_decisions,
                data_sufficiency=a.data_sufficiency.level,
            ))

        # Add drift findings
        findings.extend(drift_findings)

        latency_ms = int((time.monotonic() - start_time) * 1000)

        log.info(
            "calibration_completed",
            total_decisions=len(context.decisions),
            finding_count=len(findings),
            drift_count=len(drift_detections),
            latency_ms=latency_ms,
        )

        return CalibrationResult(
            decision_distribution=decision_dist,
            risk_level_distribution=risk_dist,
            signal_distribution=signal_dist,
            policy_summaries=policy_summaries,
            agent_summaries=agent_summaries,
            drift_detections=drift_detections,
            findings=findings,
            data_sufficiency=data_suff,
            computed_at=now.isoformat(),
            window_days=context.window_days,
            total_decisions_analyzed=len(context.decisions),
        )


def _compute_sufficiency(count: int) -> DataSufficiency:
    """Determine overall data sufficiency."""
    for threshold, level_str in SUFFICIENCY_THRESHOLDS:
        if count >= threshold:
            level = DataSufficiencyLevel(level_str)
            return DataSufficiency(
                sample_count=count,
                level=level,
                explanation=f"{count} decisions — {level_str} confidence",
            )
    return DataSufficiency(
        sample_count=count,
        level=DataSufficiencyLevel.INSUFFICIENT,
        explanation=f"{count} decisions — insufficient data",
    )

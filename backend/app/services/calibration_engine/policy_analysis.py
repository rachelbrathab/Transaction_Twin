"""Policy analysis for calibration.

Extracts policy information from Decision.explanation JSONB.
Pure functions — no I/O, no database, no side effects.
"""

from __future__ import annotations

from app.services.calibration_engine.constants import (
    POLICY_HIGH_TRIGGER_RATE,
    POLICY_MIN_EVALUATIONS,
)
from app.services.calibration_engine.models import (
    CalibrationContext,
    PolicyDecisionSummary,
)


def analyze_policies(ctx: CalibrationContext) -> list[PolicyDecisionSummary]:
    """Analyze policy behavior from decision explanations."""
    # Build policy lookup from context
    policy_lookup = {p.policy_id: p for p in ctx.policies}

    # Aggregate per-policy statistics
    policy_stats: dict[str, dict[str, int | str | None]] = {}

    for d in ctx.decisions:
        policy_statuses = d.explanation.get("policy_statuses", {})
        triggered_names = d.explanation.get("triggered_policy_names", [])

        if not isinstance(policy_statuses, dict):
            continue

        for pid, status in policy_statuses.items():
            if pid not in policy_stats:
                policy_stats[pid] = {
                    "evaluation_count": 0,
                    "trigger_count": 0,
                    "invalid_count": 0,
                    "allow": 0,
                    "review": 0,
                    "block": 0,
                    "highest_severity": None,
                }

            stats = policy_stats[pid]
            stats["evaluation_count"] = int(stats["evaluation_count"]) + 1

            if status == "triggered":
                stats["trigger_count"] = int(stats["trigger_count"]) + 1
            elif status == "invalid_policy":
                stats["invalid_count"] = int(stats["invalid_count"]) + 1

            # Track which decisions this policy was associated with
            if d.decision == "allow":
                stats["allow"] = int(stats["allow"]) + 1
            elif d.decision == "review":
                stats["review"] = int(stats["review"]) + 1
            elif d.decision == "block":
                stats["block"] = int(stats["block"]) + 1

            # Track highest severity from triggered policies
            if status == "triggered" and pid in triggered_names:
                policy_info = d.explanation.get("policy", {})
                highest = policy_info.get("highest_severity")
                if highest is not None:
                    existing = stats["highest_severity"]
                    if existing is None or _sev_rank(highest) > _sev_rank(
                        str(existing)
                    ):
                        stats["highest_severity"] = highest

    summaries = []
    for pid, stats in policy_stats.items():
        eval_count = int(stats["evaluation_count"])
        trigger_count = int(stats["trigger_count"])
        invalid_count = int(stats["invalid_count"])

        trigger_rate = (
            round(trigger_count / eval_count, 4) if eval_count > 0 else 0.0
        )

        policy_meta = policy_lookup.get(pid)
        policy_name = policy_meta.policy_name if policy_meta else pid

        summaries.append(PolicyDecisionSummary(
            policy_id=pid,
            policy_name=policy_name,
            evaluation_count=eval_count,
            trigger_count=trigger_count,
            trigger_rate=trigger_rate,
            invalid_count=invalid_count,
            highest_severity_seen=str(stats["highest_severity"])
            if stats["highest_severity"] is not None else None,
            associated_allow=int(stats["allow"]),
            associated_review=int(stats["review"]),
            associated_block=int(stats["block"]),
        ))

    # Sort by evaluation count descending
    summaries.sort(key=lambda s: s.evaluation_count, reverse=True)
    return summaries


def get_high_trigger_policies(
    summaries: list[PolicyDecisionSummary],
) -> list[PolicyDecisionSummary]:
    """Identify policies with unusually high trigger rates."""
    flagged = []
    for s in summaries:
        if (
            s.evaluation_count >= POLICY_MIN_EVALUATIONS
            and s.trigger_rate > POLICY_HIGH_TRIGGER_RATE
        ):
            flagged.append(s)
    return flagged


_SEV_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _sev_rank(sev: str) -> int:
    return _SEV_ORDER.get(sev.lower(), 0)

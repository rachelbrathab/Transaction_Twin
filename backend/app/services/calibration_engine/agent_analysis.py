"""Agent-level calibration analysis.

Uses AuditEvent.metadata_["intent_id"] → Intent.agent_id for attribution.
Pure functions — no I/O, no database, no side effects.
"""

from __future__ import annotations

from app.services.calibration_engine.constants import (
    AGENT_UNSTABLE_BLOCK_RATE,
    AGENT_UNSTABLE_REVIEW_RATE,
)
from app.services.calibration_engine.models import (
    AgentDecisionSummary,
    CalibrationContext,
    DataSufficiency,
    DataSufficiencyLevel,
)


def analyze_agents(ctx: CalibrationContext) -> list[AgentDecisionSummary]:
    """Analyze per-agent decision patterns.

    Attribution is via: Decision → AuditEvent.intent_id → Intent.agent_id.
    Agent information comes from ctx.agents.
    """
    agent_lookup = {a.agent_id: a for a in ctx.agents}

    # Aggregate by intent_id (which maps to agent_id)
    # We use intent_id from decision records
    agent_stats: dict[str, dict[str, int | float]] = {}

    for d in ctx.decisions:
        intent_id = d.intent_id

        # Resolve agent attribution
        agent_id = _resolve_agent_id(intent_id, ctx)
        if agent_id is None:
            continue

        if agent_id not in agent_stats:
            agent_stats[agent_id] = {
                "total": 0,
                "allow": 0,
                "review": 0,
                "block": 0,
                "signal_count_sum": 0,
                "drift_none": 0,
                "drift_low": 0,
                "drift_medium": 0,
                "drift_high": 0,
                "drift_critical": 0,
                "policy_triggered_sum": 0,
            }

        stats = agent_stats[agent_id]
        stats["total"] = int(stats["total"]) + 1
        stats["signal_count_sum"] = int(stats["signal_count_sum"]) + d.signal_count
        stats["policy_triggered_sum"] = (
            int(stats["policy_triggered_sum"]) + d.policy_triggered_count
        )

        if d.decision == "allow":
            stats["allow"] = int(stats["allow"]) + 1
        elif d.decision == "review":
            stats["review"] = int(stats["review"]) + 1
        elif d.decision == "block":
            stats["block"] = int(stats["block"]) + 1

        # Drift severity distribution
        ds = d.drift_severity
        if ds and isinstance(ds, str):
            key = f"drift_{ds}"
            if key in stats:
                stats[key] = int(stats[key]) + 1

    summaries = []
    for agent_id, stats in agent_stats.items():
        total = int(stats["total"])
        if total == 0:
            continue

        allow = int(stats["allow"])
        review = int(stats["review"])
        block = int(stats["block"])

        agent_meta = agent_lookup.get(agent_id)
        agent_name = agent_meta.agent_name if agent_meta else None
        rep_snapshot = (
            agent_meta.reputation_snapshot if agent_meta else None
        )
        rep_score = None
        if isinstance(rep_snapshot, dict):
            rep_score = rep_snapshot.get("overall_score")

        suff = _sufficiency(total)

        summaries.append(AgentDecisionSummary(
            agent_id=agent_id,
            agent_name=agent_name,
            total_decisions=total,
            allow_rate=round(allow / total, 4),
            review_rate=round(review / total, 4),
            block_rate=round(block / total, 4),
            avg_signal_count=round(
                int(stats["signal_count_sum"]) / total, 2
            ),
            drift_severity_distribution={
                "none": int(stats["drift_none"]),
                "low": int(stats["drift_low"]),
                "medium": int(stats["drift_medium"]),
                "high": int(stats["drift_high"]),
                "critical": int(stats["drift_critical"]),
            },
            reputation_score=rep_score,
            data_sufficiency=suff,
        ))

    summaries.sort(key=lambda s: s.total_decisions, reverse=True)
    return summaries


def identify_unstable_agents(
    summaries: list[AgentDecisionSummary],
) -> list[AgentDecisionSummary]:
    """Identify agents with unstable decision patterns."""
    unstable = []
    for s in summaries:
        if (
            s.review_rate > AGENT_UNSTABLE_REVIEW_RATE
            or s.block_rate > AGENT_UNSTABLE_BLOCK_RATE
        ):
            unstable.append(s)
    return unstable


def _resolve_agent_id(intent_id: str, ctx: CalibrationContext) -> str | None:
    """Resolve agent_id from intent_id.

    Uses filter_agent_id when available (API-level filtering).
    When exactly one agent exists, attributes all decisions to that agent.
    Multiple agents without explicit filter: cannot resolve.
    """
    # If filtered to a single agent, all decisions belong to that agent
    if ctx.filter_agent_id is not None:
        return ctx.filter_agent_id

    # If we have exactly one agent, attribute all to that agent
    if len(ctx.agents) == 1:
        return ctx.agents[0].agent_id

    # Multiple agents: cannot resolve without intent→agent mapping
    # This is a known limitation documented in the architecture
    return None


def _sufficiency(count: int) -> DataSufficiency:
    """Determine data sufficiency for an agent."""
    if count >= 100:
        return DataSufficiency(
            sample_count=count,
            level=DataSufficiencyLevel.HIGH,
            explanation=f"{count} decisions — high confidence",
        )
    if count >= 30:
        return DataSufficiency(
            sample_count=count,
            level=DataSufficiencyLevel.MODERATE,
            explanation=f"{count} decisions — moderate confidence",
        )
    if count >= 10:
        return DataSufficiency(
            sample_count=count,
            level=DataSufficiencyLevel.LOW,
            explanation=f"{count} decisions — low confidence",
        )
    return DataSufficiency(
        sample_count=count,
        level=DataSufficiencyLevel.INSUFFICIENT,
        explanation=f"{count} decisions — insufficient for reliable patterns",
    )

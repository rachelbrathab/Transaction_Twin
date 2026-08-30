"""Analytics endpoint — decision calibration dashboard.

GET /api/v1/analytics/calibration — read-only analysis of historical decisions.
Does NOT modify policies, risk weights, thresholds, or reputation.
Does NOT execute payments or call LLMs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.identity import get_current_user
from app.models.agent import Agent
from app.models.audit_event import AuditEvent
from app.models.decision import Decision
from app.models.intent import Intent
from app.models.policy import Policy
from app.models.user import User
from app.services.calibration_engine.constants import (
    MAX_DECISIONS,
    MAX_HISTORY_DAYS,
)
from app.services.calibration_engine.engine import CalibrationEngine
from app.services.calibration_engine.models import (
    AgentRecord,
    CalibrationContext,
    DecisionRecord,
    PolicyRecord,
)

logger = structlog.get_logger()
router = APIRouter()


class CalibrationResponse(BaseModel):
    """API response for calibration analysis."""

    decision_distribution: dict
    risk_level_distribution: dict
    signal_distribution: dict
    policy_summaries: list[dict] = Field(default_factory=list)
    agent_summaries: list[dict] = Field(default_factory=list)
    drift_detections: list[dict] = Field(default_factory=list)
    findings: list[dict] = Field(default_factory=list)
    data_sufficiency: dict
    merchant_analysis: str = ""
    computed_at: str = ""
    window_days: int = 30
    total_decisions_analyzed: int = 0


@router.get("/analytics/calibration", response_model=CalibrationResponse)
async def get_calibration(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    window_days: int = Query(default=30, ge=1, le=90),
    agent_id: uuid.UUID | None = Query(default=None),
    policy_id: uuid.UUID | None = Query(default=None),
) -> CalibrationResponse:
    """Analyze historical decision patterns for calibration insights.

    Read-only analysis of the decision system's behavior over time.
    Does not modify policies, risk weights, thresholds, or reputation.
    """
    try:
        return await _get_calibration_impl(
            db, window_days, current_user.id, agent_id, policy_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("calibration_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Calibration analysis failed",
        ) from e


async def _get_calibration_impl(
    db: AsyncSession,
    window_days: int,
    user_id: uuid.UUID | None,
    agent_id: uuid.UUID | None,
    policy_id: uuid.UUID | None,
) -> CalibrationResponse:
    """Implementation of calibration endpoint."""
    now = datetime.now(UTC)
    window_start = now - timedelta(days=min(window_days, MAX_HISTORY_DAYS))

    # ── Query 1: Decisions (bounded) ───────────────────────────
    decision_query = (
        select(Decision)
        .where(Decision.created_at >= window_start)
        .order_by(Decision.created_at.desc())
        .limit(MAX_DECISIONS)
    )
    if policy_id is not None:
        decision_query = decision_query.where(Decision.policy_id == policy_id)

    result = await db.execute(decision_query)
    decision_models = result.scalars().all()

    # ── Query 2: Audit events for these decisions (bounded) ────
    decision_ids = [d.id for d in decision_models]
    if not decision_ids:
        return _empty_response(window_days, now)

    audit_query = (
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == "decision",
            AuditEvent.entity_id.in_(decision_ids),
        )
        .order_by(AuditEvent.created_at.desc())
    )
    audit_result = await db.execute(audit_query)
    audit_events = audit_result.scalars().all()
    audit_lookup = {ae.entity_id: ae for ae in audit_events}

    # ── Query 3: Intents for agent attribution (bounded) ───────
    intent_ids = set()
    for ae in audit_events:
        meta = ae.metadata_ or {}
        iid = meta.get("intent_id")
        if iid:
            try:
                intent_ids.add(uuid.UUID(iid))
            except (ValueError, TypeError):
                pass

    intent_agent_map: dict[str, str] = {}
    agent_ids_from_intents: set[uuid.UUID] = set()

    if intent_ids:
        intent_query = select(Intent).where(Intent.id.in_(list(intent_ids)))
        intent_result = await db.execute(intent_query)
        intents = intent_result.scalars().all()
        for intent in intents:
            intent_agent_map[str(intent.id)] = str(intent.agent_id)
            agent_ids_from_intents.add(intent.agent_id)

    # ── Query 4: Agents (bounded) ──────────────────────────────
    agent_ids_to_load = list(agent_ids_from_intents)
    if agent_id is not None:
        agent_ids_to_load = [agent_id]

    agents = []
    if agent_ids_to_load:
        agent_query = select(Agent).where(Agent.id.in_(agent_ids_to_load))
        agent_result = await db.execute(agent_query)
        agents = agent_result.scalars().all()

    # ── Query 5: Policies (bounded) ────────────────────────────
    policy_ids = set()
    for d in decision_models:
        if d.policy_id:
            policy_ids.add(d.policy_id)
    if policy_id is not None:
        policy_ids.add(policy_id)

    policies = []
    if policy_ids:
        policy_query = select(Policy).where(Policy.id.in_(list(policy_ids)))
        policy_result = await db.execute(policy_query)
        policies = policy_result.scalars().all()

    # ── Build CalibrationContext ────────────────────────────────
    decision_records = []
    for d in decision_models:
        ae = audit_lookup.get(d.id)
        meta = ae.metadata_ if ae else {}

        intent_id_str = None
        if meta and isinstance(meta, dict):
            raw_iid = meta.get("intent_id")
            if raw_iid:
                intent_id_str = str(raw_iid)

        # Resolve agent_id from intent mapping
        agent_id_str = intent_agent_map.get(intent_id_str) if intent_id_str else None
        if agent_id and agent_id_str != str(agent_id):
            continue

        decision_records.append(DecisionRecord(
            decision_id=str(d.id),
            decision=d.decision,
            policy_id=str(d.policy_id) if d.policy_id else None,
            reason=d.reason,
            explanation=d.explanation or {},
            version=d.version,
            created_at=d.created_at.isoformat() if d.created_at else "",
            evaluation_id=meta.get("evaluation_id") if isinstance(meta, dict) else None,
            intent_id=intent_id_str,
            signal_count=meta.get("signal_count", 0) if isinstance(meta, dict) else 0,
            policy_triggered_count=(
                meta.get("policy_triggered_count", 0)
                if isinstance(meta, dict) else 0
            ),
            drift_severity=meta.get("drift_severity") if isinstance(meta, dict) else None,
            risk_available=meta.get("risk_available", False) if isinstance(meta, dict) else False,
        ))

    agent_records = [
        AgentRecord(
            agent_id=str(a.id),
            agent_name=a.name,
            reputation_snapshot=a.reputation_snapshot,
        )
        for a in agents
    ]

    policy_records = [
        PolicyRecord(
            policy_id=str(p.id),
            policy_name=p.name,
            policy_version=p.version,
        )
        for p in policies
    ]

    ctx = CalibrationContext(
        user_id=str(user_id) if user_id else "",
        decisions=decision_records,
        agents=agent_records,
        policies=policy_records,
        window_days=window_days,
        baseline_window_days=window_days * 2,
        filter_agent_id=str(agent_id) if agent_id else None,
        filter_policy_id=str(policy_id) if policy_id else None,
    )

    # ── Run Calibration Engine ──────────────────────────────────
    engine = CalibrationEngine()
    result = engine.evaluate(ctx)

    return CalibrationResponse(
        decision_distribution=result.decision_distribution.model_dump(),
        risk_level_distribution=result.risk_level_distribution.model_dump(),
        signal_distribution=result.signal_distribution.model_dump(),
        policy_summaries=[p.model_dump() for p in result.policy_summaries],
        agent_summaries=[a.model_dump() for a in result.agent_summaries],
        drift_detections=[d.model_dump() for d in result.drift_detections],
        findings=[f.model_dump() for f in result.findings],
        data_sufficiency=result.data_sufficiency.model_dump(),
        merchant_analysis=result.merchant_analysis,
        computed_at=result.computed_at,
        window_days=result.window_days,
        total_decisions_analyzed=result.total_decisions_analyzed,
    )


def _empty_response(window_days: int, now: datetime) -> CalibrationResponse:
    """Return an empty calibration response."""
    from app.services.calibration_engine.models import (
        DataSufficiency,
        DataSufficiencyLevel,
        DecisionDistribution,
        RiskLevelDistribution,
        SignalContributionDistribution,
    )

    return CalibrationResponse(
        decision_distribution=DecisionDistribution(
            total=0, allow_count=0, review_count=0, block_count=0,
            allow_rate=0.0, review_rate=0.0, block_rate=0.0, sample_count=0,
        ).model_dump(),
        risk_level_distribution=RiskLevelDistribution(
            total_with_risk=0, low_count=0, medium_count=0,
            high_count=0, critical_count=0, risk_unavailable_count=0,
        ).model_dump(),
        signal_distribution=SignalContributionDistribution(
            total_decisions=0,
        ).model_dump(),
        data_sufficiency=DataSufficiency(
            sample_count=0,
            level=DataSufficiencyLevel.INSUFFICIENT,
            explanation="No decisions found",
        ).model_dump(),
        computed_at=now.isoformat(),
        window_days=window_days,
        total_decisions_analyzed=0,
    )

"""Decision Engine endpoint.

POST /api/v1/transactions/decide — produces ALLOW / REVIEW / BLOCK disposition.
Does NOT execute payments or call payment APIs.
Does NOT call LLMs.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import validate_agent_belongs_to_user
from app.models.agent import Agent
from app.models.audit_event import AuditEvent
from app.models.decision import Decision
from app.models.intent import Intent
from app.models.policy import Policy
from app.models.transaction import Transaction
from app.schemas.decision_engine import (
    DecisionRequest,
    DecisionResponse,
    DecisionSignalResponse,
    DriftSummaryResponse,
    PolicySummaryResponse,
    RiskSummaryResponse,
)
from app.services.comparison_engine.engine import ComparisonEngine
from app.services.comparison_engine.models import TransactionProposal
from app.services.decision_engine.engine import DecisionEngine
from app.services.decision_engine.models import DecisionContext
from app.services.graph_risk_engine.engine import GraphRiskEngine
from app.services.graph_risk_engine.models import (
    AgentTransactionRecord,
    GraphContext,
    MerchantPeerRecord,
    SiblingAgentRecord,
)
from app.services.intent_engine.models import StructuredIntent
from app.services.policy_engine.evaluator import PolicyEvaluator
from app.services.policy_engine.models import EvaluationContext
from app.services.reputation_engine.engine import ReputationEngine
from app.services.reputation_engine.models import BehavioralContext
from app.services.risk_engine.engine import RiskEngine
from app.services.risk_engine.models import RiskContext, VelocityContext

logger = structlog.get_logger()
router = APIRouter()


# Maximum time window for velocity queries (1 week)
VELOCITY_WINDOW_WEEKS = 1
VELOCITY_MAX_ROWS = 500

# Reputation snapshot cache: recompute at most once per hour
REPUTATION_CACHE_SECONDS = 3600
# History window for reputation computation (90 days)
REPUTATION_WINDOW_DAYS = 90
REPUTATION_MAX_ROWS = 1000

# Graph Risk Engine (Sprint 9)
GRAPH_WINDOW_DAYS = 90
GRAPH_MAX_ROWS = 500
GRAPH_MAX_MERCHANT_AGENTS = 100
GRAPH_MAX_SIBLING_AGENTS = 50


async def _build_velocity_context(
    db: AsyncSession,
    agent_id: uuid.UUID,
) -> VelocityContext:
    """Pre-compute velocity features with a single bounded query."""
    now = datetime.now(UTC)
    one_week_ago = now - timedelta(weeks=VELOCITY_WINDOW_WEEKS)

    result = await db.execute(
        select(Transaction)
        .where(Transaction.agent_id == agent_id)
        .where(Transaction.created_at >= one_week_ago)
        .order_by(Transaction.created_at.desc())
        .limit(VELOCITY_MAX_ROWS)
    )
    recent = result.scalars().all()

    if not recent:
        return VelocityContext(history_available=False)

    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(days=1)

    hour_txns = [t for t in recent if t.created_at >= one_hour_ago]
    day_txns = [t for t in recent if t.created_at >= one_day_ago]

    hour_amounts = [Decimal(str(t.amount)) for t in hour_txns]
    day_amounts = [Decimal(str(t.amount)) for t in day_txns]

    day_merchants = {t.merchant_id for t in day_txns if t.merchant_id}
    hour_merchant_counts: dict[uuid.UUID, int] = {}
    hour_type_counts: dict[str, int] = {}
    for t in hour_txns:
        if t.merchant_id:
            hour_merchant_counts[t.merchant_id] = (
                hour_merchant_counts.get(t.merchant_id, 0) + 1
            )
        hour_type_counts[t.transaction_type] = (
            hour_type_counts.get(t.transaction_type, 0) + 1
        )

    return VelocityContext(
        transactions_last_hour=len(hour_txns),
        transactions_last_day=len(day_txns),
        transactions_last_week=len(recent),
        total_amount_last_hour=(
            sum(hour_amounts) if hour_amounts else None
        ),
        total_amount_last_day=(
            sum(day_amounts) if day_amounts else None
        ),
        average_amount_last_day=(
            Decimal(str(sum(day_amounts) / len(day_amounts)))
            if day_amounts
            else None
        ),
        same_merchant_count_last_hour=(
            max(hour_merchant_counts.values()) if hour_merchant_counts else 0
        ),
        same_type_count_last_hour=(
            max(hour_type_counts.values()) if hour_type_counts else 0
        ),
        unique_merchants_last_day=len(day_merchants),
        history_available=True,
    )


async def _build_behavioral_context(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
) -> BehavioralContext:
    """Build BehavioralContext for reputation computation.

    Uses bounded queries with a 90-day window and 1000-row limit.
    Extracts decision outcomes, policy violations, drift events,
    amount patterns, merchant diversity, and risk history.
    """
    now = datetime.now(UTC)
    window_start = now - timedelta(days=REPUTATION_WINDOW_DAYS)
    recent_window = now - timedelta(days=30)

    # Single bounded query for transaction history
    result = await db.execute(
        select(Transaction)
        .where(Transaction.agent_id == agent_id)
        .where(Transaction.created_at >= window_start)
        .order_by(Transaction.created_at.desc())
        .limit(REPUTATION_MAX_ROWS)
    )
    transactions = result.scalars().all()

    if not transactions:
        return BehavioralContext(
            agent_id=str(agent_id),
            user_id=str(user_id),
            history_available=False,
            decision_history_available=False,
            risk_history_available=False,
        )

    # Transaction counts
    total = len(transactions)
    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(days=1)
    one_week_ago = now - timedelta(weeks=1)
    one_month_ago = now - timedelta(days=30)

    txns_last_hour = sum(1 for t in transactions if t.created_at >= one_hour_ago)
    txns_last_day = sum(1 for t in transactions if t.created_at >= one_day_ago)
    txns_last_week = sum(1 for t in transactions if t.created_at >= one_week_ago)
    txns_last_month = sum(1 for t in transactions if t.created_at >= one_month_ago)

    # Amount patterns
    amounts = [float(t.amount) for t in transactions if t.amount is not None]
    avg_amount = sum(amounts) / len(amounts) if amounts else None
    max_amount = max(amounts) if amounts else None
    amount_stddev = None
    if avg_amount is not None and len(amounts) >= 2:
        variance = sum((a - avg_amount) ** 2 for a in amounts) / len(amounts)
        amount_stddev = variance ** 0.5

    # Merchant diversity
    all_merchants = {t.merchant_id for t in transactions if t.merchant_id}
    week_merchants = {
        t.merchant_id for t in transactions
        if t.merchant_id and t.created_at >= one_week_ago
    }

    # Temporal patterns
    first_txn = min(t.created_at for t in transactions)
    last_txn = max(t.created_at for t in transactions)
    account_age_days = max(0, (now - first_txn).days)

    # Load decisions for this agent (bounded)
    from app.models.decision import Decision
    decision_result = await db.execute(
        select(Decision)
        .join(Transaction, Decision.transaction_id == Transaction.id)
        .where(Transaction.agent_id == agent_id)
        .where(Decision.created_at >= window_start)
        .order_by(Decision.created_at.desc())
        .limit(REPUTATION_MAX_ROWS)
    )
    decisions = decision_result.scalars().all()

    # Decision outcomes
    total_decisions = len(decisions)
    allow_count = sum(1 for d in decisions if d.decision == "allow")
    review_count = sum(1 for d in decisions if d.decision == "review")
    block_count = sum(1 for d in decisions if d.decision == "block")

    recent_decisions = [d for d in decisions if d.created_at >= recent_window]
    recent_allow = sum(1 for d in recent_decisions if d.decision == "allow")
    recent_review = sum(1 for d in recent_decisions if d.decision == "review")
    recent_block = sum(1 for d in recent_decisions if d.decision == "block")

    # Extract policy violations from Decision.explanation JSONB
    total_policy_violations = 0
    recent_policy_violations = 0
    critical_violations = 0
    high_violations = 0
    total_drift_events = 0
    critical_drift_count = 0
    high_drift_count = 0

    for d in decisions:
        explanation = d.explanation or {}
        policy_statuses = explanation.get("policy_statuses", {})
        for _pid, status in policy_statuses.items():
            if status == "triggered":
                total_policy_violations += 1
                if d.created_at >= recent_window:
                    recent_policy_violations += 1
        # Check drift from explanation
        drift_info = explanation.get("drift", {})
        drift_severity = drift_info.get("severity")
        if drift_severity and drift_severity in ("medium", "high", "critical"):
            total_drift_events += 1
            if drift_severity == "critical":
                critical_drift_count += 1
            elif drift_severity == "high":
                high_drift_count += 1

    # Load risk assessments for this agent (bounded)
    from app.models.risk_assessment import RiskAssessment
    risk_result_q = await db.execute(
        select(RiskAssessment)
        .join(Transaction, RiskAssessment.transaction_id == Transaction.id)
        .where(Transaction.agent_id == agent_id)
        .where(RiskAssessment.created_at >= window_start)
        .order_by(RiskAssessment.created_at.desc())
        .limit(REPUTATION_MAX_ROWS)
    )
    risk_assessments = risk_result_q.scalars().all()

    risk_scores = [
        ra.overall_score for ra in risk_assessments
        if ra.overall_score is not None
    ]
    avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else None
    max_risk = max(risk_scores) if risk_scores else None
    critical_risk = sum(1 for s in risk_scores if s >= 0.75)

    return BehavioralContext(
        agent_id=str(agent_id),
        user_id=str(user_id),
        total_transactions=total,
        transactions_last_hour=txns_last_hour,
        transactions_last_day=txns_last_day,
        transactions_last_week=txns_last_week,
        transactions_last_month=txns_last_month,
        total_decisions=total_decisions,
        allow_count=allow_count,
        review_count=review_count,
        block_count=block_count,
        recent_allow_count=recent_allow,
        recent_review_count=recent_review,
        recent_block_count=recent_block,
        total_policy_violations=total_policy_violations,
        recent_policy_violations=recent_policy_violations,
        critical_violations=critical_violations,
        high_violations=high_violations,
        total_drift_events=total_drift_events,
        critical_drift_count=critical_drift_count,
        high_drift_count=high_drift_count,
        average_transaction_amount=avg_amount,
        max_transaction_amount=max_amount,
        amount_stddev=amount_stddev,
        unique_merchants_all_time=len(all_merchants),
        unique_merchants_last_week=len(week_merchants),
        first_transaction_at=first_txn.isoformat(),
        last_transaction_at=last_txn.isoformat(),
        account_age_days=account_age_days,
        average_risk_score=avg_risk,
        max_risk_score=max_risk,
        critical_risk_count=critical_risk,
        history_available=True,
        decision_history_available=total_decisions > 0,
        risk_history_available=len(risk_assessments) > 0,
    )


async def _build_graph_context(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
) -> GraphContext:
    """Build GraphContext for network risk analysis.

    Uses bounded queries with a 90-day window.
    Extracts agent transactions, merchant peers, and sibling agents.
    """
    now = datetime.now(UTC)
    window_start = now - timedelta(days=GRAPH_WINDOW_DAYS)

    # Query 1: Agent's own transactions (bounded)
    result = await db.execute(
        select(Transaction)
        .where(Transaction.agent_id == agent_id)
        .where(Transaction.created_at >= window_start)
        .order_by(Transaction.created_at.desc())
        .limit(GRAPH_MAX_ROWS)
    )
    agent_txns = result.scalars().all()

    if not agent_txns:
        return GraphContext(
            target_agent_id=str(agent_id),
            target_user_id=str(user_id),
            graph_available=False,
        )

    # Extract unique merchant IDs from agent's transactions
    merchant_ids = list({t.merchant_id for t in agent_txns if t.merchant_id})

    # Query 2: Other agents' transactions at same merchants (bounded)
    merchant_peers: list[MerchantPeerRecord] = []
    if merchant_ids:
        peer_result = await db.execute(
            select(Transaction)
            .where(Transaction.merchant_id.in_(merchant_ids))
            .where(Transaction.agent_id != agent_id)
            .where(Transaction.created_at >= window_start)
            .order_by(Transaction.created_at.desc())
            .limit(GRAPH_MAX_MERCHANT_AGENTS)
        )
        peer_txns = peer_result.scalars().all()

        # Group by agent_id to get per-agent summaries
        peer_agents: dict[uuid.UUID, list[Transaction]] = {}
        for pt in peer_txns:
            if pt.agent_id not in peer_agents:
                peer_agents[pt.agent_id] = []
            peer_agents[pt.agent_id].append(pt)

        # Load trust scores for peer agents
        peer_agent_ids = list(peer_agents.keys())
        if peer_agent_ids:
            agent_trust_result = await db.execute(
                select(Agent.id, Agent.trust_score)
                .where(Agent.id.in_(peer_agent_ids))
            )
            trust_map = {
                row.id: float(row.trust_score) if row.trust_score else None
                for row in agent_trust_result
            }

            for peer_agent_id, peer_txn_list in peer_agents.items():
                # Find which merchant this peer shares with the target agent
                shared_merchant_ids = {
                    t.merchant_id for t in peer_txn_list if t.merchant_id
                } & set(merchant_ids)
                for mid in shared_merchant_ids:
                    merchant_peers.append(MerchantPeerRecord(
                        agent_id=str(peer_agent_id),
                        merchant_id=str(mid),
                        trust_score=trust_map.get(peer_agent_id),
                        transaction_count=len(peer_txn_list),
                        latest_transaction_at=(
                            peer_txn_list[0].created_at.isoformat()
                            if peer_txn_list else ""
                        ),
                    ))

    # Query 3: Sibling agents under the same user (bounded)
    sibling_result = await db.execute(
        select(Agent)
        .where(Agent.user_id == user_id)
        .where(Agent.id != agent_id)
        .limit(GRAPH_MAX_SIBLING_AGENTS)
    )
    sibling_models = sibling_result.scalars().all()

    # Query 4: Sibling transaction counts (single bounded query)
    sibling_txn_counts: dict[uuid.UUID, int] = {}
    if sibling_models:
        sibling_ids = [sa.id for sa in sibling_models]
        sibling_txn_result = await db.execute(
            select(Transaction.agent_id)
            .where(Transaction.agent_id.in_(sibling_ids))
            .where(Transaction.created_at >= window_start)
        )
        for row in sibling_txn_result:
            sid = row[0]
            sibling_txn_counts[sid] = sibling_txn_counts.get(sid, 0) + 1

    sibling_agents: list[SiblingAgentRecord] = []
    for sa in sibling_models:
        sibling_agents.append(SiblingAgentRecord(
            agent_id=str(sa.id),
            name=sa.name,
            trust_score=float(sa.trust_score) if sa.trust_score else None,
            status=sa.status,
            transaction_count=sibling_txn_counts.get(sa.id, 0),
        ))

    # Build agent transaction records
    agent_txn_records = [
        AgentTransactionRecord(
            transaction_id=str(t.id),
            merchant_id=str(t.merchant_id) if t.merchant_id else None,
            amount=float(t.amount),
            currency=t.currency,
            transaction_type=t.transaction_type,
            created_at=t.created_at.isoformat(),
        )
        for t in agent_txns
    ]

    return GraphContext(
        target_agent_id=str(agent_id),
        target_user_id=str(user_id),
        agent_transactions=agent_txn_records,
        merchant_peer_records=merchant_peers,
        sibling_agents=sibling_agents,
        history_window_days=GRAPH_WINDOW_DAYS,
        graph_available=True,
    )


@router.post("/transactions/decide", response_model=DecisionResponse)
async def decide_transaction(
    request: DecisionRequest,
    db: AsyncSession = Depends(get_db),
) -> DecisionResponse:
    """Produce a deterministic transaction disposition.

    Returns ALLOW / REVIEW / BLOCK based on intent, drift, policy, and trust signals.
    Does NOT execute payments or call external services.
    """
    try:
        return await _decide_transaction_impl(request, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("decision_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Internal decision engine error",
        ) from e


async def _decide_transaction_impl(
    request: DecisionRequest,
    db: AsyncSession,
) -> DecisionResponse:
    """Implementation of the decision endpoint."""
    # 1. Parse proposal
    try:
        proposal = TransactionProposal(**request.proposal)
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid proposal: {e}",
        )

    # 2. Validate intent exists
    try:
        intent_uuid = uuid.UUID(request.intent_id)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid intent_id format: {request.intent_id}",
        )

    intent_result = await db.execute(
        select(Intent).where(Intent.id == intent_uuid)
    )
    intent_model = intent_result.scalar_one_or_none()

    if intent_model is None:
        raise HTTPException(status_code=404, detail="Intent not found")

    # 3. Validate ownership
    try:
        user_uuid = uuid.UUID(proposal.user_id)
        agent_uuid = uuid.UUID(proposal.agent_id)
        await validate_agent_belongs_to_user(db, user_uuid, agent_uuid)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    # 4. Validate intent ownership
    if intent_model.user_id != user_uuid:
        raise HTTPException(
            status_code=403,
            detail="Intent does not belong to the specified user",
        )
    if intent_model.agent_id != agent_uuid:
        raise HTTPException(
            status_code=403,
            detail="Intent does not belong to the specified agent",
        )

    # 5. Reconstruct StructuredIntent
    if intent_model.structured_intent is None:
        raise HTTPException(
            status_code=422,
            detail="Intent has no structured data",
        )

    try:
        structured_intent = StructuredIntent(**intent_model.structured_intent)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reconstruct intent: {e}",
        )

    # 6. Run Transaction Twin
    try:
        comparison_engine = ComparisonEngine()
        drift_result = comparison_engine.compare(
            intent=structured_intent,
            proposal=proposal,
            intent_id=str(intent_model.id),
            intent_version=intent_model.version,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Transaction Twin comparison failed: {e}",
        )

    # 7. Load active policies and run Policy Engine
    policy_result_model = await db.execute(
        select(Policy).where(Policy.user_id == user_uuid)
    )
    all_policies = policy_result_model.scalars().all()

    policy_dicts = [
        {
            "id": str(p.id),
            "name": p.name,
            "version": p.version,
            "status": p.status,
            "rules": p.rules,
            "scope": p.scope,
            "effective_from": (
                p.effective_from.isoformat() if p.effective_from else None
            ),
            "effective_until": (
                p.effective_until.isoformat() if p.effective_until else None
            ),
        }
        for p in all_policies
    ]

    # Build EvaluationContext for Policy Engine
    amount_deviation = None
    for fc in drift_result.field_comparisons:
        if (
            fc.field == "amount"
            and fc.drift is not None
            and fc.drift.deviation_percent is not None
        ):
            amount_deviation = fc.drift.deviation_percent
            break

    policy_context = EvaluationContext(
        proposal_amount=proposal.amount,
        proposal_currency=proposal.currency,
        proposal_transaction_type=proposal.transaction_type.value,
        proposal_category=proposal.category,
        proposal_merchant_name=proposal.merchant_name,
        proposal_merchant_trusted=proposal.merchant_trusted,
        proposal_country=proposal.country,
        proposal_city=proposal.city,
        proposal_scheduled_at=proposal.scheduled_at,
        proposal_authorization_scope=(
            proposal.authorization_scope.value
            if proposal.authorization_scope
            else None
        ),
        intent_transaction_type=structured_intent.transaction_type.value,
        intent_currency=structured_intent.currency.code,
        intent_amount_min=structured_intent.amount.min,
        intent_amount_max=structured_intent.amount.max,
        intent_category=(
            structured_intent.category_constraints.items[0]
            if structured_intent.category_constraints.items
            else None
        ),
        intent_merchant_trust_required=(
            structured_intent.merchant_constraints.trust_required
        ),
        drift_overall_status=drift_result.overall_status.value,
        drift_severity=drift_result.drift_severity.value,
        drift_amount_status=next(
            (fc.status.value for fc in drift_result.field_comparisons if fc.field == "amount"),
            None,
        ),
        drift_amount_deviation_percent=amount_deviation,
        drift_currency_status=next(
            (fc.status.value for fc in drift_result.field_comparisons if fc.field == "currency"),
            None,
        ),
        drift_category_status=next(
            (fc.status.value for fc in drift_result.field_comparisons if fc.field == "category"),
            None,
        ),
        drift_merchant_status=next(
            (fc.status.value for fc in drift_result.field_comparisons if fc.field == "merchant"),
            None,
        ),
        drift_geographic_status=next(
            (fc.status.value for fc in drift_result.field_comparisons if fc.field == "geographic"),
            None,
        ),
        drift_temporal_status=next(
            (fc.status.value for fc in drift_result.field_comparisons if fc.field == "temporal"),
            None,
        ),
        drift_transaction_type_status=next(
            (fc.status.value for fc in drift_result.field_comparisons
             if fc.field == "transaction_type"),
            None,
        ),
        drift_authorization_scope_status=next(
            (fc.status.value for fc in drift_result.field_comparisons
             if fc.field == "authorization_scope"),
            None,
        ),
        user_id=proposal.user_id,
        agent_id=proposal.agent_id,
    )

    policy_evaluator = PolicyEvaluator()
    policy_result = policy_evaluator.evaluate(
        policies=policy_dicts,
        context=policy_context,
        intent_id=str(intent_model.id),
        proposal_intent_id=proposal.intent_id,
    )

    # 8. Load agent trust score
    agent_result = await db.execute(
        select(Agent).where(Agent.id == agent_uuid)
    )
    agent_model = agent_result.scalar_one_or_none()
    agent_trust_score = float(agent_model.trust_score) if (
        agent_model and agent_model.trust_score is not None
    ) else None

    # 9. Build VelocityContext (single bounded query)
    velocity_context = await _build_velocity_context(db, agent_uuid)

    # 9.5. Compute Agent Reputation (Sprint 8)
    agent_reputation_score: float | None = None
    agent_reputation_level: str | None = None
    reputation_available = False

    if agent_model is not None:
        # Check if cached reputation is recent enough
        previous_snapshot = agent_model.reputation_snapshot
        snapshot_is_fresh = False
        if previous_snapshot and isinstance(previous_snapshot, dict):
            evaluated_at_str = previous_snapshot.get("evaluated_at", "")
            if evaluated_at_str:
                try:
                    evaluated_at = datetime.fromisoformat(evaluated_at_str)
                    age_seconds = (datetime.now(UTC) - evaluated_at).total_seconds()
                    snapshot_is_fresh = age_seconds < REPUTATION_CACHE_SECONDS
                except (ValueError, TypeError):
                    pass

        if snapshot_is_fresh and previous_snapshot:
            # Reuse cached reputation
            agent_reputation_score = previous_snapshot.get("overall_score")
            agent_reputation_level = previous_snapshot.get("trust_level")
            reputation_available = agent_reputation_score is not None
        else:
            # Build BehavioralContext and compute new reputation
            behavioral_context = await _build_behavioral_context(
                db=db,
                agent_id=agent_uuid,
                user_id=user_uuid,
            )

            reputation_engine = ReputationEngine()
            reputation_result = reputation_engine.evaluate(
                behavioral_context, previous_snapshot
            )

            agent_reputation_score = reputation_result.overall_score
            agent_reputation_level = reputation_result.trust_level.value
            reputation_available = True

            # Persist reputation snapshot to Agent
            agent_model.reputation_snapshot = reputation_result.model_dump()
            await db.flush()

    # 9.6. Compute Graph Risk (Sprint 9)
    network_risk_result = None
    try:
        graph_context = await _build_graph_context(
            db=db,
            agent_id=agent_uuid,
            user_id=user_uuid,
        )
        graph_risk_engine = GraphRiskEngine()
        network_risk_result = graph_risk_engine.evaluate(graph_context)
    except Exception as e:
        logger.warning("graph_risk_error", error=str(e))
        network_risk_result = None

    # 10. Build RiskContext and run Risk Engine
    # Find amount deviation from drift field comparisons
    amount_deviation_for_risk = None
    for fc in drift_result.field_comparisons:
        if (
            fc.field == "amount"
            and fc.drift is not None
            and fc.drift.deviation_percent is not None
        ):
            amount_deviation_for_risk = fc.drift.deviation_percent
            break

    risk_context = RiskContext(
        user_id=proposal.user_id,
        agent_id=proposal.agent_id,
        intent_id=str(intent_model.id),
        intent_version=intent_model.version,
        intent_confidence=(
            float(intent_model.confidence) if intent_model.confidence else None
        ),
        intent_transaction_type=structured_intent.transaction_type.value,
        intent_amount_max=structured_intent.amount.max,
        intent_amount_min=structured_intent.amount.min,
        intent_currency=structured_intent.currency.code,
        intent_merchant_trust_required=(
            structured_intent.merchant_constraints.trust_required
        ),
        intent_country=structured_intent.geographic_constraints.country,
        proposal_amount=proposal.amount,
        proposal_currency=proposal.currency,
        proposal_transaction_type=proposal.transaction_type.value,
        proposal_merchant_name=proposal.merchant_name,
        proposal_merchant_trusted=proposal.merchant_trusted,
        proposal_country=proposal.country,
        drift_available=True,
        drift_overall_status=drift_result.overall_status.value,
        drift_severity=drift_result.drift_severity.value,
        drift_amount_deviation_percent=amount_deviation_for_risk,
        policy_available=True,
        policy_triggered_count=policy_result.triggered_count,
        policy_unknown_count=policy_result.unknown_count,
        policy_invalid_count=policy_result.invalid_count,
        policy_highest_severity=(
            policy_result.highest_severity.value
            if policy_result.highest_severity
            else None
        ),
        agent_trust_score=agent_trust_score,
        agent_reputation_score=agent_reputation_score,
        agent_reputation_level=agent_reputation_level,
        agent_reputation_available=reputation_available,
        velocity=velocity_context,
        # Sprint 9: Network risk fields
        network_risk_available=(
            network_risk_result is not None
        ),
        network_risk_score=(
            network_risk_result.overall_score
            if network_risk_result
            else None
        ),
        network_risk_confidence=(
            network_risk_result.confidence
            if network_risk_result
            else None
        ),
        network_risk_shared_exposure_score=(
            next(
                (s.score for s in network_risk_result.signals
                 if s.signal_type.value == "shared_risk_exposure"),
                None,
            )
            if network_risk_result
            else None
        ),
        network_risk_concentration_score=(
            next(
                (s.score for s in network_risk_result.signals
                 if s.signal_type.value == "merchant_concentration"),
                None,
            )
            if network_risk_result
            else None
        ),
        network_risk_cluster_risk_score=(
            next(
                (s.score for s in network_risk_result.signals
                 if s.signal_type.value == "agent_cluster_risk"),
                None,
            )
            if network_risk_result
            else None
        ),
    )

    risk_engine = RiskEngine()
    risk_result = risk_engine.evaluate(risk_context)

    # 11. Build DecisionContext
    # Serialize policy results for the Decision Engine
    policy_results_for_signals = []
    for pr in policy_result.policy_results:
        categories = []
        for rr in pr.rule_results:
            if rr.category and rr.category not in categories:
                categories.append(rr.category)
        policy_results_for_signals.append({
            "policy_id": pr.policy_id,
            "policy_name": pr.policy_name,
            "policy_version": pr.policy_version,
            "status": pr.status.value,
            "highest_triggered_severity": pr.highest_triggered_severity.value,
            "categories": categories,
        })

    decision_context = DecisionContext(
        user_id=proposal.user_id,
        agent_id=proposal.agent_id,
        agent_trust_score=agent_trust_score,
        intent_id=str(intent_model.id),
        intent_version=intent_model.version,
        intent_status=intent_model.status,
        intent_confidence=(
            float(intent_model.confidence) if intent_model.confidence else None
        ),
        intent_transaction_type=structured_intent.transaction_type.value,
        proposal_intent_id=proposal.intent_id,
        proposal_transaction_type=proposal.transaction_type.value,
        proposal_amount=proposal.amount,
        proposal_currency=proposal.currency,
        proposal_merchant_name=proposal.merchant_name,
        proposal_merchant_trusted=proposal.merchant_trusted,
        proposal_country=proposal.country,
        drift_result_available=True,
        drift_overall_status=drift_result.overall_status.value,
        drift_severity=drift_result.drift_severity.value,
        policy_result_available=True,
        policy_triggered_count=policy_result.triggered_count,
        policy_unknown_count=policy_result.unknown_count,
        policy_invalid_count=policy_result.invalid_count,
        policy_highest_triggered_severity=(
            policy_result.highest_severity.value
            if policy_result.highest_severity
            else None
        ),
        policy_results_for_signals=policy_results_for_signals,
        risk_result=risk_result,
    )

    # 12. Run Decision Engine
    decision_engine = DecisionEngine()
    decision_result = decision_engine.evaluate(decision_context)

    # 13. Persist Decision
    # Find the most-severe triggered policy for policy_id FK
    most_severe_policy_id = None
    for pr_dict in policy_results_for_signals:
        if pr_dict["status"] == "triggered":
            try:
                most_severe_policy_id = uuid.UUID(pr_dict["policy_id"])
            except (ValueError, KeyError):
                pass
            break  # First triggered is ordered by severity

    explanation_data = {
        **decision_result.explanation,
        "policy_ids": [pr["policy_id"] for pr in policy_results_for_signals],
        "policy_versions": {
            pr["policy_id"]: pr["policy_version"]
            for pr in policy_results_for_signals
        },
        "policy_statuses": {
            pr["policy_id"]: pr["status"] for pr in policy_results_for_signals
        },
        "triggered_policy_names": (
            decision_result.policy_summary.triggered_policy_names
            if decision_result.policy_summary
            else []
        ),
    }

    db_decision = Decision(
        transaction_id=None,  # No Transaction record yet in Sprint 6
        risk_assessment_id=None,  # Risk Engine not available in Sprint 6
        policy_id=most_severe_policy_id,
        decision=decision_result.decision.value,
        reason=decision_result.reason,
        explanation=explanation_data,
        version=1,
    )
    db.add(db_decision)
    await db.flush()

    # 14. Create AuditEvent
    audit_event = AuditEvent(
        entity_type="decision",
        entity_id=db_decision.id,
        event_type="decision_created",
        actor_type="system",
        actor_id=None,
        metadata_={
            "decision": decision_result.decision.value,
            "evaluation_id": decision_result.evaluation_id,
            "intent_id": decision_result.intent_id,
            "decision_version": decision_result.decision_version,
            "signal_count": decision_result.signal_count,
            "policy_triggered_count": (
                decision_result.policy_summary.triggered_count
                if decision_result.policy_summary
                else 0
            ),
            "drift_severity": (
                decision_result.drift_summary.severity
                if decision_result.drift_summary
                else None
            ),
            "risk_available": True,
        },
    )
    db.add(audit_event)
    await db.flush()

    # 15. Build response
    return DecisionResponse(
        decision=decision_result.decision.value,
        reason=decision_result.reason,
        decision_version=decision_result.decision_version,
        evaluation_id=decision_result.evaluation_id,
        intent_id=decision_result.intent_id,
        intent_version=decision_result.intent_version,
        proposal_intent_id=decision_result.proposal_intent_id,
        policy_summary=(
            PolicySummaryResponse(
                total_policies=decision_result.policy_summary.total_policies,
                triggered_count=decision_result.policy_summary.triggered_count,
                unknown_count=decision_result.policy_summary.unknown_count,
                invalid_count=decision_result.policy_summary.invalid_count,
                highest_triggered_severity=(
                    decision_result.policy_summary.highest_triggered_severity
                ),
                triggered_policy_names=(
                    decision_result.policy_summary.triggered_policy_names
                ),
                triggered_policy_categories=(
                    decision_result.policy_summary.triggered_policy_categories
                ),
            )
            if decision_result.policy_summary
            else None
        ),
        risk_summary=(
            RiskSummaryResponse(
                overall_score=risk_result.overall_score,
                risk_level=risk_result.risk_level.value,
                available=True,
            )
        ),
        drift_summary=(
            DriftSummaryResponse(
                overall_status=decision_result.drift_summary.overall_status,
                severity=decision_result.drift_summary.severity,
                mismatch_count=decision_result.drift_summary.mismatch_count,
            )
            if decision_result.drift_summary
            else None
        ),
        signals=[
            DecisionSignalResponse(
                source=s.source,
                signal_type=s.signal_type,
                status=s.status,
                severity=s.severity,
                description=s.description,
                evidence=s.evidence,
            )
            for s in decision_result.signals
        ],
        signal_count=decision_result.signal_count,
        explanation=decision_result.explanation,
        created_at=decision_result.created_at,
        evaluated_at=decision_result.evaluated_at,
    )

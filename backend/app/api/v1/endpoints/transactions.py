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
from app.services.intent_engine.models import StructuredIntent
from app.services.policy_engine.evaluator import PolicyEvaluator
from app.services.policy_engine.models import EvaluationContext
from app.services.risk_engine.engine import RiskEngine
from app.services.risk_engine.models import RiskContext, VelocityContext

logger = structlog.get_logger()
router = APIRouter()


# Maximum time window for velocity queries (1 week)
VELOCITY_WINDOW_WEEKS = 1
VELOCITY_MAX_ROWS = 500


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
        velocity=velocity_context,
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

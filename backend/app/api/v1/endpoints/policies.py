"""Policy evaluation endpoint.

POST /api/v1/policies/evaluate — evaluates security/business policies against a proposal.
Does NOT make ALLOW/REVIEW/BLOCK decisions — that belongs to the future Decision Engine.
Does NOT execute payments or call payment APIs.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import validate_agent_belongs_to_user
from app.models.intent import Intent
from app.models.policy import Policy
from app.schemas.policy_evaluation import (
    ConditionResultResponse,
    PolicyEvaluationRequest,
    PolicyEvaluationResponse,
    PolicyResultResponse,
    RuleResultResponse,
)
from app.services.comparison_engine.engine import ComparisonEngine
from app.services.comparison_engine.models import TransactionProposal
from app.services.intent_engine.models import StructuredIntent
from app.services.policy_engine.evaluator import PolicyEvaluator
from app.services.policy_engine.models import EvaluationContext

logger = structlog.get_logger()
router = APIRouter()


@router.post("/policies/evaluate", response_model=PolicyEvaluationResponse)
async def evaluate_policies(
    request: PolicyEvaluationRequest,
    db: AsyncSession = Depends(get_db),
) -> PolicyEvaluationResponse:
    """Evaluate applicable security policies against a proposed transaction.

    Returns per-policy evaluation results with PASS/TRIGGERED/UNKNOWN/INVALID_POLICY.
    Does NOT make ALLOW/REVIEW/BLOCK decision or execute payment.
    """
    try:
        return await _evaluate_policies_impl(request, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("policy_evaluation_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Internal policy evaluation error",
        ) from e


async def _evaluate_policies_impl(
    request: PolicyEvaluationRequest,
    db: AsyncSession,
) -> PolicyEvaluationResponse:
    """Implementation of the policy evaluation endpoint."""
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

    if intent_model.status != "active":
        raise HTTPException(
            status_code=422,
            detail=f"Intent is not active (status: {intent_model.status})",
        )

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

    # 6. Run Transaction Twin to get DriftResult
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

    # 7. Build EvaluationContext
    # Find the amount drift deviation percent from field comparisons
    amount_deviation = None
    for fc in drift_result.field_comparisons:
        if fc.field == "amount" and fc.drift is not None and fc.drift.deviation_percent is not None:
            amount_deviation = fc.drift.deviation_percent
            break

    context = EvaluationContext(
        # Proposal
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
            proposal.authorization_scope.value if proposal.authorization_scope else None
        ),
        # Intent
        intent_transaction_type=structured_intent.transaction_type.value,
        intent_currency=structured_intent.currency.code,
        intent_amount_min=(
            structured_intent.amount.min
            if structured_intent.amount.min is not None
            else None
        ),
        intent_amount_max=(
            structured_intent.amount.max
            if structured_intent.amount.max is not None
            else None
        ),
        intent_category=(
            structured_intent.category_constraints.items[0]
            if structured_intent.category_constraints.items
            else None
        ),
        intent_merchant_trust_required=structured_intent.merchant_constraints.trust_required,
        # Drift
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
        # Identity
        user_id=proposal.user_id,
        agent_id=proposal.agent_id,
    )

    # 8. Load applicable active policies for this user
    policy_result = await db.execute(
        select(Policy).where(Policy.user_id == user_uuid)
    )
    all_policies = policy_result.scalars().all()

    # Convert to dicts for the evaluator
    policy_dicts = [
        {
            "id": str(p.id),
            "name": p.name,
            "version": p.version,
            "status": p.status,
            "rules": p.rules,
            "scope": p.scope,
            "effective_from": p.effective_from.isoformat() if p.effective_from else None,
            "effective_until": p.effective_until.isoformat() if p.effective_until else None,
        }
        for p in all_policies
    ]

    # 9. Run Policy Engine
    evaluator = PolicyEvaluator()
    result = evaluator.evaluate(
        policies=policy_dicts,
        context=context,
        intent_id=str(intent_model.id),
        proposal_intent_id=proposal.intent_id,
    )

    # 10. Build response
    return PolicyEvaluationResponse(
        intent_id=result.intent_id,
        proposal_intent_id=result.proposal_intent_id,
        evaluation_id=result.evaluation_id,
        policy_results=[
            PolicyResultResponse(
                policy_id=pr.policy_id,
                policy_version=pr.policy_version,
                policy_name=pr.policy_name,
                status=pr.status,
                rule_results=[
                    RuleResultResponse(
                        name=rr.name,
                        description=rr.description,
                        category=rr.category,
                        severity=rr.severity,
                        status=rr.status,
                        condition_results=[
                            ConditionResultResponse(
                                field=cr.field,
                                operator=cr.operator,
                                expected_value=cr.expected_value,
                                observed_value=cr.observed_value,
                                status=cr.status,
                                explanation=cr.explanation,
                            )
                            for cr in rr.condition_results
                        ],
                        explanation=rr.explanation,
                    )
                    for rr in pr.rule_results
                ],
                matched_rule_count=pr.matched_rule_count,
                triggered_rule_count=pr.triggered_rule_count,
                unknown_rule_count=pr.unknown_rule_count,
                highest_triggered_severity=pr.highest_triggered_severity,
                explanation=pr.explanation,
            )
            for pr in result.policy_results
        ],
        total_policies=result.total_policies,
        triggered_count=result.triggered_count,
        unknown_count=result.unknown_count,
        invalid_count=result.invalid_count,
        pass_count=result.pass_count,
        highest_severity=result.highest_severity,
        summary=result.summary,
        evaluated_at=result.evaluated_at,
        evaluator_version=result.evaluator_version,
    )

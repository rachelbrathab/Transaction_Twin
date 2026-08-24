"""Comparison endpoint.

POST /api/v1/comparisons/compare — compares a proposed transaction against a parsed intent.
Does NOT execute payments, authorize transactions, or call payment APIs.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import validate_agent_belongs_to_user
from app.models.intent import Intent
from app.schemas.comparison import ComparisonRequest, ComparisonResponse
from app.services.comparison_engine.engine import ComparisonEngine
from app.services.comparison_engine.models import TransactionProposal

logger = structlog.get_logger()
router = APIRouter()


@router.post("/comparisons/compare", response_model=ComparisonResponse)
async def compare_proposal(
    request: ComparisonRequest,
    db: AsyncSession = Depends(get_db),
) -> ComparisonResponse:
    """Compare a proposed transaction against a parsed intent.

    Returns DriftResult with field-level comparison results.
    Does NOT execute payment or create a Decision.
    """
    try:
        return await _compare_proposal_impl(request, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("comparison_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Internal comparison error",
        ) from e


async def _compare_proposal_impl(
    request: ComparisonRequest,
    db: AsyncSession,
) -> ComparisonResponse:
    """Implementation of the comparison endpoint."""
    # Parse proposal from request
    try:
        proposal = TransactionProposal(**request.proposal)
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid proposal: {e}",
        )

    # Validate intent exists
    try:
        intent_uuid = uuid.UUID(proposal.intent_id)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid intent_id format: {proposal.intent_id}",
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

    # Validate ownership
    try:
        user_uuid = uuid.UUID(proposal.user_id)
        agent_uuid = uuid.UUID(proposal.agent_id)
        await validate_agent_belongs_to_user(db, user_uuid, agent_uuid)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    # Validate intent ownership matches proposal
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

    # Reconstruct StructuredIntent from DB
    if intent_model.structured_intent is None:
        raise HTTPException(
            status_code=422,
            detail="Intent has no structured data",
        )

    from app.services.intent_engine.models import StructuredIntent

    try:
        structured_intent = StructuredIntent(**intent_model.structured_intent)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reconstruct intent: {e}",
        )

    # Run comparison
    engine = ComparisonEngine()
    result = engine.compare(
        intent=structured_intent,
        proposal=proposal,
        intent_id=str(intent_model.id),
        intent_version=intent_model.version,
    )

    # Build response
    return ComparisonResponse(
        intent_id=result.intent_id,
        intent_version=result.intent_version,
        proposal_intent_id=result.proposal_intent_id,
        overall_status=result.overall_status,
        drift_severity=result.drift_severity,
        field_comparisons=[
            {
                "field": fc.field,
                "status": fc.status,
                "drift_category": fc.drift_category.value,
                "severity": fc.severity,
                "intent_value": fc.intent_value,
                "intent_evidence": fc.intent_evidence,
                "proposal_value": fc.proposal_value,
                "explanation": fc.explanation,
                "drift": fc.drift.model_dump() if fc.drift else None,
            }
            for fc in result.field_comparisons
        ],
        match_count=result.match_count,
        mismatch_count=result.mismatch_count,
        unknown_count=result.unknown_count,
        not_applicable_count=result.not_applicable_count,
        intent_confidence=result.intent_confidence,
        summary=result.summary,
        rejection_reason=result.rejection_reason,
        compared_at=result.compared_at,
        comparator_version=result.comparator_version,
    )

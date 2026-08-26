"""Manual Review API endpoint.

POST /api/v1/transactions/{transaction_id}/review — approve or reject a REVIEW decision.

Does NOT execute payments. Does NOT call LLMs.
"""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.audit_event import AuditEvent
from app.models.decision import Decision
from app.models.transaction import Transaction
from app.models.transaction_event import TransactionEvent
from app.services.outcome_engine.models import OutcomeEventType

logger = structlog.get_logger()
router = APIRouter()


# ── Request / Response schemas ─────────────────────────────────────


class ReviewRequest(BaseModel):
    """Request body for manual review."""

    action: str = Field(
        ...,
        description="Review action: 'approve' or 'reject'",
    )
    reason: str | None = Field(
        default=None,
        description="Optional reason for the review decision",
    )
    actor_id: str | None = Field(
        default=None,
        description="ID of the human reviewer",
    )


class ReviewResponse(BaseModel):
    """Response body for manual review."""

    transaction_id: str
    decision_id: str
    action: str
    status: str
    override_status: str
    created_at: str


# ── Endpoint ───────────────────────────────────────────────────────


@router.post(
    "/transactions/{transaction_id}/review",
    response_model=ReviewResponse,
)
async def review_transaction(
    transaction_id: uuid.UUID,
    request: ReviewRequest,
    user_id: uuid.UUID = Query(..., description="User ID for ownership validation"),
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    """Approve or reject a transaction with REVIEW decision.

    Only transactions in DECIDED status with an original REVIEW decision
    can be reviewed.
    """
    try:
        return await _review_transaction_impl(transaction_id, request, user_id, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("review_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Internal review processing error",
        ) from e


async def _review_transaction_impl(
    transaction_id: uuid.UUID,
    request: ReviewRequest,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> ReviewResponse:
    """Implementation of manual review."""
    # 1. Validate action
    action = request.action.lower().strip()
    if action not in ("approve", "reject"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action: {request.action}. Must be 'approve' or 'reject'.",
        )

    # 2. Load transaction
    txn_result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    transaction = txn_result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found",
        )

    # 3. Validate ownership
    if transaction.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Transaction does not belong to the specified user",
        )

    # 4. Validate transaction status
    if transaction.status != "decided":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Transaction is in '{transaction.status}' status. "
                "Only transactions in 'decided' status can be reviewed."
            ),
        )

    # 5. Load the decision
    decision_result = await db.execute(
        select(Decision)
        .where(Decision.transaction_id == transaction_id)
        .order_by(Decision.version.desc())
        .limit(1)
    )
    decision = decision_result.scalar_one_or_none()

    if decision is None:
        raise HTTPException(
            status_code=404,
            detail="No decision found for this transaction",
        )

    # 6. Validate original decision was REVIEW
    if decision.decision != "review":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Original decision was '{decision.decision}', not 'review'. "
                "Only REVIEW decisions can be overridden."
            ),
        )

    # 7. Check for duplicate review
    if decision.override_status is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Decision already reviewed: {decision.override_status}",
        )

    # 8. Determine event type and next status
    if action == "approve":
        event_type = OutcomeEventType.MANUAL_APPROVED
        next_status = "approved"
        override_status = "approved"
    else:
        event_type = OutcomeEventType.MANUAL_REJECTED
        next_status = "rejected"
        override_status = "rejected"

    # 9. Get next sequence number
    seq_result = await db.execute(
        select(TransactionEvent)
        .where(TransactionEvent.transaction_id == transaction_id)
        .order_by(TransactionEvent.sequence_number.desc())
        .limit(1)
    )
    last_event = seq_result.scalar_one_or_none()
    next_sequence = (last_event.sequence_number + 1) if last_event else 1

    # 10. Create TransactionEvent
    event_id = str(uuid.uuid4())
    db_event = TransactionEvent(
        id=uuid.UUID(event_id),
        transaction_id=transaction_id,
        agent_id=transaction.agent_id,
        sequence_number=next_sequence,
        event_type=event_type.value,
        source="manual_review",
        verification_state="verified",
        payload={
            "action": action,
            "reason": request.reason,
            "actor_id": request.actor_id,
        },
    )
    db.add(db_event)

    # 11. Update Decision with override
    decision.override_status = override_status
    decision.override_actor_id = request.actor_id
    decision.override_reason = request.reason

    # 12. Update Transaction status
    transaction.status = next_status

    # 13. Create AuditEvent
    audit_event = AuditEvent(
        entity_type="decision",
        entity_id=decision.id,
        event_type="manual_review",
        actor_type="manual_review",
        actor_id=None,
        metadata_={
            "event_id": event_id,
            "action": action,
            "override_status": override_status,
            "actor_id": request.actor_id,
            "reason": request.reason,
        },
    )
    db.add(audit_event)

    await db.flush()

    logger.info(
        "manual_review_completed",
        transaction_id=str(transaction_id),
        decision_id=str(decision.id),
        action=action,
        override_status=override_status,
    )

    return ReviewResponse(
        transaction_id=str(transaction_id),
        decision_id=str(decision.id),
        action=action,
        status=next_status,
        override_status=override_status,
        created_at=datetime.now(UTC).isoformat(),
    )

"""Outcome Engine API endpoint.

POST /api/v1/transactions/{transaction_id}/outcomes — ingest lifecycle events.

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
from app.models.transaction import Transaction
from app.models.transaction_event import TransactionEvent
from app.services.outcome_engine.models import (
    OutcomeEventType,
    OutcomeSource,
    VerificationState,
)
from app.services.outcome_engine.state_machine import (
    validate_event_order,
    validate_transition,
)

logger = structlog.get_logger()
router = APIRouter()


# ── Request / Response schemas ─────────────────────────────────────


class OutcomeRequest(BaseModel):
    """Request body for outcome event ingestion."""

    event_type: str = Field(
        ...,
        description="Event type (e.g. payment_success, chargeback_received)",
    )
    source: str = Field(
        ...,
        description="Event source (e.g. payment_provider, admin, system)",
    )
    provider: str | None = Field(
        default=None,
        description="Payment provider name if applicable",
    )
    external_event_id: str | None = Field(
        default=None,
        description="Provider's external event ID for idempotency",
    )
    provider_timestamp: datetime | None = Field(
        default=None,
        description="Timestamp from the external provider",
    )
    payload: dict | None = Field(
        default=None,
        description="Additional event metadata",
    )
    verification_state: str | None = Field(
        default=None,
        description="Override verification state (default: auto-determined)",
    )


class OutcomeResponse(BaseModel):
    """Response body for outcome ingestion."""

    event_id: str
    transaction_id: str
    event_type: str
    status: str
    sequence_number: int
    idempotent: bool = False
    created_at: str


# ── Endpoint ───────────────────────────────────────────────────────


@router.post(
    "/transactions/{transaction_id}/outcomes",
    response_model=OutcomeResponse,
)
async def create_outcome(
    transaction_id: uuid.UUID,
    request: OutcomeRequest,
    user_id: uuid.UUID = Query(..., description="User ID for ownership validation"),
    db: AsyncSession = Depends(get_db),
) -> OutcomeResponse:
    """Ingest an outcome event for a transaction.

    Validates state transitions, event ordering, and idempotency.
    Creates a TransactionEvent and updates Transaction.status.
    """
    try:
        return await _create_outcome_impl(transaction_id, request, user_id, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("outcome_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Internal outcome processing error",
        ) from e


async def _create_outcome_impl(
    transaction_id: uuid.UUID,
    request: OutcomeRequest,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> OutcomeResponse:
    """Implementation of outcome ingestion."""
    # 1. Validate event type
    try:
        event_type = OutcomeEventType(request.event_type)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid event_type: {request.event_type}",
        )

    # 2. Validate source
    try:
        source = OutcomeSource(request.source)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid source: {request.source}",
        )

    # 3. Load transaction
    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found",
        )

    # 4. Validate ownership
    if transaction.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Transaction does not belong to the specified user",
        )

    # 5. Determine verification state
    if request.verification_state:
        try:
            verification_state = VerificationState(request.verification_state)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid verification_state: {request.verification_state}",
            )
    else:
        # Auto-determine based on source
        if source.value in ("payment_provider", "admin"):
            verification_state = VerificationState.VERIFIED
        else:
            verification_state = VerificationState.PENDING

    # 6. Idempotency check
    if request.external_event_id and request.provider:
        existing = await db.execute(
            select(TransactionEvent).where(
                TransactionEvent.transaction_id == transaction_id,
                TransactionEvent.provider == request.provider,
                TransactionEvent.external_event_id == request.external_event_id,
            )
        )
        existing_event = existing.scalar_one_or_none()
        if existing_event is not None:
            return OutcomeResponse(
                event_id=str(existing_event.id),
                transaction_id=str(transaction_id),
                event_type=existing_event.event_type,
                status=transaction.status,
                sequence_number=existing_event.sequence_number,
                idempotent=True,
                created_at=existing_event.created_at.isoformat(),
            )

    # 7. Validate state transition
    is_valid, next_status, error_msg = validate_transition(
        transaction.status, event_type.value
    )
    if not is_valid:
        raise HTTPException(
            status_code=409,
            detail=error_msg or "Invalid state transition",
        )

    # 8. Get next sequence number
    seq_result = await db.execute(
        select(TransactionEvent)
        .where(TransactionEvent.transaction_id == transaction_id)
        .order_by(TransactionEvent.sequence_number.desc())
        .limit(1)
    )
    last_event = seq_result.scalar_one_or_none()
    next_sequence = (last_event.sequence_number + 1) if last_event else 1

    # 9. Validate event ordering
    if last_event:
        is_order_valid, order_error = validate_event_order(
            previous_timestamp=last_event.created_at,
            current_timestamp=datetime.now(UTC),
            previous_sequence=last_event.sequence_number,
            current_sequence=next_sequence,
        )
        if not is_order_valid:
            raise HTTPException(
                status_code=409,
                detail=order_error or "Event ordering violation",
            )

    # 10. Create TransactionEvent
    event_id = str(uuid.uuid4())
    db_event = TransactionEvent(
        id=uuid.UUID(event_id),
        transaction_id=transaction_id,
        agent_id=transaction.agent_id,
        sequence_number=next_sequence,
        event_type=event_type.value,
        source=source.value,
        verification_state=verification_state.value,
        provider=request.provider,
        external_event_id=request.external_event_id,
        payload=request.payload or {},
    )
    db.add(db_event)

    # 11. Update Transaction status
    transaction.status = next_status

    # 12. Create AuditEvent
    audit_event = AuditEvent(
        entity_type="transaction",
        entity_id=transaction_id,
        event_type="outcome_received",
        actor_type=source.value,
        actor_id=None,
        metadata_={
            "event_id": event_id,
            "event_type": event_type.value,
            "source": source.value,
            "verification_state": verification_state.value,
            "next_status": next_status,
            "sequence_number": next_sequence,
        },
    )
    db.add(audit_event)

    await db.flush()

    logger.info(
        "outcome_event_created",
        transaction_id=str(transaction_id),
        event_type=event_type.value,
        next_status=next_status,
        sequence_number=next_sequence,
    )

    return OutcomeResponse(
        event_id=event_id,
        transaction_id=str(transaction_id),
        event_type=event_type.value,
        status=next_status,
        sequence_number=next_sequence,
        idempotent=False,
        created_at=datetime.now(UTC).isoformat(),
    )

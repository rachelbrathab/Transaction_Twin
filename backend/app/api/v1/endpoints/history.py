"""Transaction History API endpoint.

GET /api/v1/transactions/{transaction_id}/history — get complete lifecycle history.

Does NOT call LLMs. Read-only.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.decision import Decision
from app.models.transaction import Transaction
from app.models.transaction_event import TransactionEvent
from app.services.outcome_engine.feedback import classify_feedback

logger = structlog.get_logger()
router = APIRouter()



# ── Response schemas ───────────────────────────────────────────────


class EventRecord(BaseModel):
    """Simplified event record for history display."""

    event_id: str
    event_type: str
    source: str | None = None
    verification_state: str | None = None
    sequence_number: int
    payload: dict = Field(default_factory=dict)
    created_at: str


class FeedbackRecord(BaseModel):
    """Feedback classification for a decision."""

    feedback_type: str
    confidence: float
    reasoning: str
    decision_value: str
    outcome_event_type: str
    verification_state: str


class TransactionHistoryResponse(BaseModel):
    """Response body for transaction history."""

    transaction_id: str
    current_status: str
    decision: str | None = None
    decision_reason: str | None = None
    events: list[EventRecord] = Field(default_factory=list)
    feedback: FeedbackRecord | None = None


# ── Endpoint ───────────────────────────────────────────────────────


@router.get(
    "/transactions/{transaction_id}/history",
    response_model=TransactionHistoryResponse,
)
async def get_transaction_history(
    transaction_id: uuid.UUID,
    user_id: uuid.UUID = Query(..., description="User ID for ownership validation"),
    db: AsyncSession = Depends(get_db),
) -> TransactionHistoryResponse:
    """Get complete lifecycle history for a transaction.

    Returns all events ordered by sequence, plus feedback classification
    from verified outcome history.
    """
    try:
        return await _get_history_impl(transaction_id, user_id, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("history_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Internal history retrieval error",
        ) from e


async def _get_history_impl(
    transaction_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> TransactionHistoryResponse:
    """Implementation of history retrieval."""
    # 1. Load transaction
    txn_result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    transaction = txn_result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found",
        )

    # 2. Validate ownership
    if transaction.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Transaction does not belong to the specified user",
        )

    # 3. Load decision
    decision_result = await db.execute(
        select(Decision)
        .where(Decision.transaction_id == transaction_id)
        .order_by(Decision.version.desc())
        .limit(1)
    )
    decision = decision_result.scalar_one_or_none()

    # 4. Load all events ordered by sequence
    events_result = await db.execute(
        select(TransactionEvent)
        .where(TransactionEvent.transaction_id == transaction_id)
        .order_by(TransactionEvent.sequence_number.asc())
    )
    events = events_result.scalars().all()

    # 5. Build event records
    event_records = [
        EventRecord(
            event_id=str(event.id),
            event_type=event.event_type,
            source=event.source,
            verification_state=event.verification_state,
            sequence_number=event.sequence_number,
            payload=event.payload or {},
            created_at=event.created_at.isoformat(),
        )
        for event in events
    ]

    # 6. Compute feedback from verified outcomes
    feedback = None
    if decision is not None:
        # Find the most recent verified outcome event (excluding decision_created)
        verified_outcome = None
        for event in reversed(events):
            if (
                event.event_type != "decision_created"
                and event.verification_state == "verified"
            ):
                verified_outcome = event
                break

        if verified_outcome is not None:
            feedback_classification = classify_feedback(
                original_decision=decision.decision,
                outcome_event_type=verified_outcome.event_type,
                verification_state=verified_outcome.verification_state,
            )
            feedback = FeedbackRecord(
                feedback_type=feedback_classification.feedback_type.value,
                confidence=feedback_classification.confidence,
                reasoning=feedback_classification.reasoning,
                decision_value=feedback_classification.decision_value,
                outcome_event_type=feedback_classification.outcome_event_type,
                verification_state=(
                    feedback_classification.verification_state.value
                ),
            )

    return TransactionHistoryResponse(
        transaction_id=str(transaction_id),
        current_status=transaction.status,
        decision=decision.decision if decision else None,
        decision_reason=decision.reason if decision else None,
        events=event_records,
        feedback=feedback,
    )

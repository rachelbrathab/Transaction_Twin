"""Transaction List API endpoint.

GET /api/v1/transactions — list transactions for the authenticated user.
GET /api/v1/transactions/{transaction_id} — get transaction detail.

Read-only. Ownership-scoped.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.identity import get_current_user
from app.models.decision import Decision
from app.models.transaction import Transaction
from app.models.user import User

logger = structlog.get_logger()
router = APIRouter()


# ── Response schemas ───────────────────────────────────────────


class TransactionListItem(BaseModel):
    """Summary of a transaction for list display."""

    id: str
    agent_id: str
    transaction_type: str
    amount: float
    currency: str
    status: str
    decision: str | None = None
    decision_reason: str | None = None
    risk_level: str | None = None
    risk_score: float | None = None
    created_at: str


class TransactionListResponse(BaseModel):
    """Paginated list of transactions."""

    transactions: list[TransactionListItem] = Field(default_factory=list)
    total: int = 0


class TransactionDetailResponse(BaseModel):
    """Full transaction detail."""

    id: str
    user_id: str
    agent_id: str
    intent_id: str
    transaction_type: str
    amount: float
    currency: str
    status: str
    decision: str | None = None
    decision_reason: str | None = None
    decision_explanation: dict | None = None
    risk_level: str | None = None
    risk_score: float | None = None
    risk_features: dict | None = None
    metadata: dict | None = None
    created_at: str
    updated_at: str
    events: list[dict] = Field(default_factory=list)


# ── List endpoint ──────────────────────────────────────────────


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> TransactionListResponse:
    """List transactions for the authenticated user.

    Returns transactions with their latest decision and risk assessment.
    Ownership-scoped — only returns the user's own transactions.
    """
    try:
        return await _list_transactions_impl(current_user.id, limit, offset, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("transaction_list_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Failed to list transactions",
        ) from e


async def _list_transactions_impl(
    user_id: uuid.UUID,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> TransactionListResponse:
    """Implementation of transaction listing."""
    # Count total
    from sqlalchemy import func

    count_result = await db.execute(
        select(func.count()).select_from(Transaction).where(
            Transaction.user_id == user_id,
        ),
    )
    total = count_result.scalar() or 0

    # Query transactions
    txn_result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.created_at.desc())
        .limit(limit)
        .offset(offset),
    )
    txns = txn_result.scalars().all()

    if not txns:
        return TransactionListResponse(total=total)

    txn_ids = [t.id for t in txns]

    # Get latest decisions for these transactions
    dec_result = await db.execute(
        select(Decision)
        .where(Decision.transaction_id.in_(txn_ids))
        .order_by(Decision.version.desc()),
    )
    decisions = dec_result.scalars().all()

    # Map transaction_id → latest decision
    decision_map: dict[uuid.UUID, Decision] = {}
    for d in decisions:
        if d.transaction_id not in decision_map:
            decision_map[d.transaction_id] = d

    # Build response items
    items: list[TransactionListItem] = []
    for t in txns:
        dec = decision_map.get(t.id)
        explanation = dec.explanation if dec else None
        risk_info = {}
        if explanation and isinstance(explanation, dict):
            risk_info = explanation.get("risk", {})

        items.append(TransactionListItem(
            id=str(t.id),
            agent_id=str(t.agent_id),
            transaction_type=t.transaction_type,
            amount=float(t.amount),
            currency=t.currency,
            status=t.status,
            decision=dec.decision if dec else None,
            decision_reason=dec.reason if dec else None,
            risk_level=risk_info.get("level") if risk_info else None,
            risk_score=risk_info.get("score") if risk_info else None,
            created_at=t.created_at.isoformat(),
        ))

    return TransactionListResponse(transactions=items, total=total)


# ── Detail endpoint ────────────────────────────────────────────


@router.get(
    "/transactions/{transaction_id}",
    response_model=TransactionDetailResponse,
)
async def get_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionDetailResponse:
    """Get full transaction detail with decision and events."""
    try:
        return await _get_transaction_impl(transaction_id, current_user.id, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("transaction_detail_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Failed to get transaction",
        ) from e


async def _get_transaction_impl(
    transaction_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> TransactionDetailResponse:
    """Implementation of transaction detail."""
    result = await db.execute(
        select(Transaction)
        .options(selectinload(Transaction.decisions))
        .options(selectinload(Transaction.events))
        .where(Transaction.id == transaction_id),
    )
    txn = result.scalar_one_or_none()

    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if txn.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get latest decision
    dec = None
    if txn.decisions:
        dec = max(txn.decisions, key=lambda d: d.version)

    explanation = dec.explanation if dec else None
    risk_info = {}
    if explanation and isinstance(explanation, dict):
        risk_info = explanation.get("risk", {})

    # Build events list
    events = [
        {
            "event_id": str(e.id),
            "event_type": e.event_type,
            "source": e.source,
            "verification_state": e.verification_state,
            "sequence_number": e.sequence_number,
            "created_at": e.created_at.isoformat(),
        }
        for e in sorted(txn.events, key=lambda e: e.sequence_number)
    ]

    return TransactionDetailResponse(
        id=str(txn.id),
        user_id=str(txn.user_id),
        agent_id=str(txn.agent_id),
        intent_id=str(txn.intent_id),
        transaction_type=txn.transaction_type,
        amount=float(txn.amount),
        currency=txn.currency,
        status=txn.status,
        decision=dec.decision if dec else None,
        decision_reason=dec.reason if dec else None,
        decision_explanation=explanation,
        risk_level=risk_info.get("level") if risk_info else None,
        risk_score=risk_info.get("score") if risk_info else None,
        risk_features=risk_info,
        metadata=txn.metadata_,
        created_at=txn.created_at.isoformat(),
        updated_at=txn.updated_at.isoformat(),
        events=events,
    )

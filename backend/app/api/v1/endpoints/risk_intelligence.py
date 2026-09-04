"""Risk Intelligence API endpoint.

GET /api/v1/risk-intelligence/summary — aggregate risk statistics.
GET /api/v1/risk-intelligence/transactions — recent risk-evaluated transactions.

Read-only. Ownership-scoped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.identity import get_current_user
from app.models.decision import Decision
from app.models.transaction import Transaction
from app.models.user import User

logger = structlog.get_logger()
router = APIRouter()


# ── Response schemas ───────────────────────────────────────────


class RiskSummaryResponse(BaseModel):
    """Aggregate risk statistics for the user."""

    total_decisions: int = 0
    allow_count: int = 0
    block_count: int = 0
    review_count: int = 0
    risk_level_distribution: dict[str, int] = Field(default_factory=dict)
    avg_risk_score: float | None = None
    high_risk_count: int = 0
    window_days: int = 30


class RiskTransactionItem(BaseModel):
    """A transaction with its risk/decision info."""

    transaction_id: str
    agent_id: str
    transaction_type: str
    amount: float
    currency: str
    status: str
    decision: str
    risk_level: str | None = None
    risk_score: float | None = None
    decision_reason: str | None = None
    created_at: str


class RiskTransactionsResponse(BaseModel):
    """List of recent risk-evaluated transactions."""

    transactions: list[RiskTransactionItem] = Field(default_factory=list)
    total: int = 0


# ── Endpoints ──────────────────────────────────────────────────


@router.get("/risk-intelligence/summary", response_model=RiskSummaryResponse)
async def get_risk_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    window_days: int = Query(30, ge=1, le=365),
) -> RiskSummaryResponse:
    """Get aggregate risk statistics for the authenticated user."""
    try:
        return await _get_risk_summary_impl(current_user.id, window_days, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("risk_summary_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get risk summary") from e


async def _get_risk_summary_impl(
    user_id: uuid.UUID,
    window_days: int,
    db: AsyncSession,
) -> RiskSummaryResponse:
    now = datetime.now(UTC)
    window_start = now - timedelta(days=window_days)

    # Get transactions in window
    txn_result = await db.execute(
        select(Transaction.id)
        .where(Transaction.user_id == user_id)
        .where(Transaction.created_at >= window_start),
    )
    txn_ids = [row[0] for row in txn_result.all()]

    if not txn_ids:
        return RiskSummaryResponse(window_days=window_days)

    # Get decisions for these transactions
    dec_result = await db.execute(
        select(Decision).where(Decision.transaction_id.in_(txn_ids)),
    )
    decisions = dec_result.scalars().all()

    total = len(decisions)
    allow_count = sum(1 for d in decisions if d.decision == "allow")
    block_count = sum(1 for d in decisions if d.decision == "block")
    review_count = sum(1 for d in decisions if d.decision == "review")

    # Risk level distribution from explanation
    risk_levels: dict[str, int] = {}
    risk_scores: list[float] = []
    high_risk = 0

    for d in decisions:
        explanation = d.explanation or {}
        risk = explanation.get("risk", {}) if isinstance(explanation, dict) else {}
        if isinstance(risk, dict):
            level = risk.get("level")
            score = risk.get("score")
            if level:
                risk_levels[level] = risk_levels.get(level, 0) + 1
            if score is not None:
                risk_scores.append(float(score))
            if level in ("high", "critical"):
                high_risk += 1

    avg_score = sum(risk_scores) / len(risk_scores) if risk_scores else None

    return RiskSummaryResponse(
        total_decisions=total,
        allow_count=allow_count,
        block_count=block_count,
        review_count=review_count,
        risk_level_distribution=risk_levels,
        avg_risk_score=round(avg_score, 4) if avg_score is not None else None,
        high_risk_count=high_risk,
        window_days=window_days,
    )


@router.get("/risk-intelligence/transactions", response_model=RiskTransactionsResponse)
async def get_risk_transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> RiskTransactionsResponse:
    """Get recent transactions with risk/decision information."""
    try:
        return await _get_risk_transactions_impl(current_user.id, limit, offset, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("risk_transactions_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get risk transactions") from e


async def _get_risk_transactions_impl(
    user_id: uuid.UUID,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> RiskTransactionsResponse:
    # Get total count
    count_result = await db.execute(
        select(func.count()).select_from(Transaction).where(
            Transaction.user_id == user_id,
        ),
    )
    total = count_result.scalar() or 0

    # Get transactions
    txn_result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.created_at.desc())
        .limit(limit)
        .offset(offset),
    )
    txns = txn_result.scalars().all()

    if not txns:
        return RiskTransactionsResponse(total=total)

    txn_ids = [t.id for t in txns]

    # Get decisions
    dec_result = await db.execute(
        select(Decision).where(Decision.transaction_id.in_(txn_ids)),
    )
    decisions = dec_result.scalars().all()
    dec_map: dict[uuid.UUID, Decision] = {}
    for d in decisions:
        if d.transaction_id not in dec_map:
            dec_map[d.transaction_id] = d

    items: list[RiskTransactionItem] = []
    for t in txns:
        dec = dec_map.get(t.id)
        explanation = dec.explanation if dec else None
        risk = {}
        if explanation and isinstance(explanation, dict):
            risk = explanation.get("risk", {})

        items.append(RiskTransactionItem(
            transaction_id=str(t.id),
            agent_id=str(t.agent_id),
            transaction_type=t.transaction_type,
            amount=float(t.amount),
            currency=t.currency,
            status=t.status,
            decision=dec.decision if dec else "unknown",
            risk_level=risk.get("level") if isinstance(risk, dict) else None,
            risk_score=risk.get("score") if isinstance(risk, dict) else None,
            decision_reason=dec.reason if dec else None,
            created_at=t.created_at.isoformat(),
        ))

    return RiskTransactionsResponse(transactions=items, total=total)

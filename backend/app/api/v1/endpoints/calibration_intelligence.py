"""Calibration Intelligence API endpoints.

Read-only advisory calibration analysis with versioned recommendations.
Does NOT modify policies, risk weights, thresholds, or reputation.
Does NOT execute payments or call LLMs.
"""

from __future__ import annotations

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
from app.services.calibration_intelligence.constants import (
    MAX_WINDOW_DAYS,
)

logger = structlog.get_logger()
router = APIRouter()


# ── Response schemas ───────────────────────────────────────────────


class SampleResponse(BaseModel):
    """Single calibration sample in the response."""

    transaction_id: str
    decision_id: str
    original_decision: str
    final_lifecycle_status: str
    feedback_type: str
    feedback_confidence: float
    verification_state: str
    risk_level: str | None = None
    risk_available: bool = False
    sample_eligible: bool = True
    exclusion_reason: str | None = None


class OutcomesResponse(BaseModel):
    """Response for calibration outcomes endpoint."""

    samples: list[SampleResponse] = Field(default_factory=list)
    total_samples: int = 0
    eligible_samples: int = 0
    excluded_samples: int = 0
    exclusion_summary: dict = Field(default_factory=dict)
    data_sufficiency: dict = Field(default_factory=dict)
    window_days: int = 30
    computed_at: str = ""


class RecommendationResponse(BaseModel):
    """Single calibration recommendation."""

    recommendation_id: str
    recommendation_type: str
    engine: str
    parameter: str | None = None
    current_value: dict | None = None
    proposed_value: dict | None = None
    evidence: dict = Field(default_factory=dict)
    sample_count: int = 0
    data_sufficiency: str = "insufficient"
    rationale: str = ""
    severity: str = "info"
    generated_at: str = ""
    calibration_version: str = ""
    status: str = "generated"


class RecommendationsListResponse(BaseModel):
    """Response for recommendations endpoint."""

    recommendations: list[RecommendationResponse] = Field(
        default_factory=list,
    )
    total: int = 0
    by_status: dict = Field(default_factory=dict)


class ReviewRequest(BaseModel):
    """Request to review a recommendation."""

    action: str = Field(
        ...,
        description="Review action: 'approve' or 'reject'",
    )
    reason: str | None = Field(
        default=None,
        description="Optional reason for the review decision",
    )


class ReviewResponse(BaseModel):
    """Response for recommendation review."""

    recommendation_id: str
    status: str
    reviewed_at: str


class ActivateRequest(BaseModel):
    """Request to activate a calibration version."""

    confirm: bool = Field(
        ...,
        description="Must be true to activate",
    )


class ActivateResponse(BaseModel):
    """Response for version activation."""

    version_id: str
    status: str
    activated_at: str
    previous_version: str | None = None
    recommendations_applied: int = 0


# ── Endpoints ──────────────────────────────────────────────────────


@router.get(
    "/analytics/calibration/outcomes",
    response_model=OutcomesResponse,
)
async def get_calibration_outcomes(
    db: AsyncSession = Depends(get_db),
    window_days: int = Query(default=30, ge=1, le=MAX_WINDOW_DAYS),
    user_id: uuid.UUID | None = Query(default=None),
) -> OutcomesResponse:
    """Get calibration dataset with eligibility information.

    Returns verified outcome samples for calibration analysis.
    """
    try:
        return await _get_outcomes_impl(db, window_days, user_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("calibration_outcomes_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Calibration outcomes retrieval failed",
        ) from e


@router.get(
    "/analytics/calibration/recommendations",
    response_model=RecommendationsListResponse,
)
async def get_calibration_recommendations(
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(default=None),
    engine: str | None = Query(default=None),
    version: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
) -> RecommendationsListResponse:
    """Get calibration recommendations.

    Returns advisory recommendations from verified outcome analysis.
    """
    try:
        return await _get_recommendations_impl(
            db, status, engine, version, user_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("calibration_recs_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Recommendations retrieval failed",
        ) from e


@router.post(
    "/analytics/calibration/recommendations/{recommendation_id}/review",
    response_model=ReviewResponse,
)
async def review_recommendation(
    recommendation_id: str,
    request: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID | None = Query(default=None),
) -> ReviewResponse:
    """Review a calibration recommendation (approve or reject)."""
    try:
        return await _review_recommendation_impl(
            db, recommendation_id, request, user_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("calibration_review_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Recommendation review failed",
        ) from e


@router.post(
    "/analytics/calibration/versions/{version_id}/activate",
    response_model=ActivateResponse,
)
async def activate_version(
    version_id: str,
    request: ActivateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID | None = Query(default=None),
) -> ActivateResponse:
    """Activate a calibration version.

    Only APPROVED recommendations are applied.
    Must pass confirm=true to activate.
    """
    try:
        return await _activate_version_impl(
            db, version_id, request, user_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("calibration_activate_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Version activation failed",
        ) from e


# ── Implementation ─────────────────────────────────────────────────


async def _get_outcomes_impl(
    db: AsyncSession,
    window_days: int,
    user_id: uuid.UUID | None,
) -> OutcomesResponse:
    """Build calibration dataset from verified outcomes."""
    from datetime import timedelta

    from app.services.calibration_intelligence.dataset import (
        build_dataset,
    )
    from app.services.calibration_intelligence.metrics import (
        compute_data_sufficiency,
    )

    now = datetime.now(UTC)
    window_start = now - timedelta(days=window_days)

    # Query transactions
    txn_result = await db.execute(
        select(Transaction)
        .where(Transaction.created_at >= window_start)
        .order_by(Transaction.created_at.desc())
        .limit(1000)
    )
    txns = txn_result.scalars().all()

    if not txns:
        return OutcomesResponse(
            window_days=window_days,
            computed_at=now.isoformat(),
        )

    txn_ids = [t.id for t in txns]

    # Query decisions for these transactions
    from app.models.decision import Decision

    dec_result = await db.execute(
        select(Decision).where(Decision.transaction_id.in_(txn_ids))
    )
    decisions = dec_result.scalars().all()

    # Query outcome events

    evt_result = await db.execute(
        select(TransactionEvent).where(
            TransactionEvent.transaction_id.in_(txn_ids),
        )
    )
    events = evt_result.scalars().all()

    # Build record dicts
    transaction_records = []
    for t in txns:
        transaction_records.append({
            "id": str(t.id),
            "user_id": str(t.user_id),
            "agent_id": str(t.agent_id),
            "status": t.status,
            "amount": float(t.amount) if t.amount else None,
            "currency": t.currency,
            "transaction_type": t.transaction_type,
            "created_at": t.created_at.isoformat()
            if t.created_at
            else "",
        })

    decision_records = []
    for d in decisions:
        explanation = d.explanation or {}
        decision_records.append({
            "id": str(d.id),
            "transaction_id": str(d.transaction_id),
            "decision": d.decision,
            "policy_id": str(d.policy_id) if d.policy_id else None,
            "explanation": explanation,
            "signal_count": 0,
            "drift_severity": None,
            "created_at": d.created_at.isoformat()
            if d.created_at
            else "",
            "feedback_confidence": 0.9,
        })

    outcome_records = []
    for e in events:
        outcome_records.append({
            "transaction_id": str(e.transaction_id),
            "event_type": e.event_type,
            "verification_state": e.verification_state or "pending",
            "created_at": e.created_at.isoformat()
            if e.created_at
            else "",
        })

    dataset = build_dataset(
        transaction_records=transaction_records,
        decision_records=decision_records,
        outcome_records=outcome_records,
        window_days=window_days,
    )

    return OutcomesResponse(
        samples=[
            SampleResponse(
                transaction_id=s.transaction_id,
                decision_id=s.decision_id,
                original_decision=s.original_decision,
                final_lifecycle_status=s.final_lifecycle_status,
                feedback_type=s.feedback_type,
                feedback_confidence=s.feedback_confidence,
                verification_state=s.verification_state,
                risk_level=s.risk_level,
                risk_available=s.risk_available,
                sample_eligible=s.sample_eligible,
                exclusion_reason=s.exclusion_reason,
            )
            for s in dataset.samples
        ],
        total_samples=dataset.total_samples,
        eligible_samples=dataset.eligible_samples,
        excluded_samples=dataset.excluded_samples,
        exclusion_summary=dataset.exclusion_summary,
        data_sufficiency={
            "sample_count": dataset.eligible_samples,
            "level": compute_data_sufficiency(
                dataset.eligible_samples
            ).value,
        },
        window_days=window_days,
        computed_at=dataset.computed_at,
    )


async def _get_recommendations_impl(
    db: AsyncSession,
    status_filter: str | None,
    engine_filter: str | None,
    version_filter: str | None,
    user_id: uuid.UUID | None,
) -> RecommendationsListResponse:
    """Get calibration recommendations from audit events."""
    # Query audit events for calibration recommendations
    query = (
        select(AuditEvent)
        .where(AuditEvent.event_type == "calibration_recommendation_generated")
        .order_by(AuditEvent.created_at.desc())
        .limit(200)
    )
    result = await db.execute(query)
    events = result.scalars().all()

    recommendations: list[RecommendationResponse] = []
    by_status: dict[str, int] = {}

    for ae in events:
        meta = ae.metadata_ or {}
        if not isinstance(meta, dict):
            continue

        rec = RecommendationResponse(
            recommendation_id=meta.get("recommendation_id", ""),
            recommendation_type=meta.get("recommendation_type", ""),
            engine=meta.get("engine", ""),
            parameter=meta.get("parameter"),
            current_value=meta.get("current_value"),
            proposed_value=meta.get("proposed_value"),
            evidence=meta.get("evidence", {}),
            sample_count=meta.get("sample_count", 0),
            data_sufficiency=meta.get("data_sufficiency", "insufficient"),
            rationale=meta.get("rationale", ""),
            severity=meta.get("severity", "info"),
            generated_at=ae.created_at.isoformat()
            if ae.created_at
            else "",
            calibration_version=meta.get("calibration_version", ""),
            status=meta.get("status", "generated"),
        )

        # Apply filters
        if status_filter and rec.status != status_filter:
            continue
        if engine_filter and rec.engine != engine_filter:
            continue
        if (
            version_filter
            and rec.calibration_version != version_filter
        ):
            continue

        recommendations.append(rec)
        by_status[rec.status] = by_status.get(rec.status, 0) + 1

    return RecommendationsListResponse(
        recommendations=recommendations,
        total=len(recommendations),
        by_status=by_status,
    )


async def _review_recommendation_impl(
    db: AsyncSession,
    recommendation_id: str,
    request: ReviewRequest,
    user_id: uuid.UUID | None,
) -> ReviewResponse:
    """Review (approve/reject) a calibration recommendation."""
    action = request.action.lower().strip()
    if action not in ("approve", "reject"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action: {request.action}. Must be 'approve' or 'reject'.",
        )

    now = datetime.now(UTC).isoformat()
    new_status = "approved" if action == "approve" else "rejected"

    # Create audit event for the review
    audit_event = AuditEvent(
        entity_type="calibration_recommendation",
        entity_id=uuid.uuid4(),  # placeholder
        event_type=f"calibration_recommendation_{action}d",
        metadata_={
            "recommendation_id": recommendation_id,
            "previous_status": "generated",
            "new_status": new_status,
            "reason": request.reason,
        },
    )
    db.add(audit_event)
    await db.flush()

    logger.info(
        "calibration_recommendation_reviewed",
        recommendation_id=recommendation_id,
        action=action,
    )

    return ReviewResponse(
        recommendation_id=recommendation_id,
        status=new_status,
        reviewed_at=now,
    )


async def _activate_version_impl(
    db: AsyncSession,
    version_id: str,
    request: ActivateRequest,
    user_id: uuid.UUID | None,
) -> ActivateResponse:
    """Activate a calibration version."""
    if not request.confirm:
        raise HTTPException(
            status_code=422,
            detail="Must pass confirm=true to activate a version",
        )

    now = datetime.now(UTC).isoformat()

    # Create audit event for activation
    audit_event = AuditEvent(
        entity_type="calibration_version",
        entity_id=uuid.uuid4(),  # placeholder
        event_type="calibration_activated",
        metadata_={
            "version_id": version_id,
            "previous_status": "generated",
            "new_status": "activated",
        },
    )
    db.add(audit_event)
    await db.flush()

    logger.info(
        "calibration_version_activated",
        version_id=version_id,
    )

    return ActivateResponse(
        version_id=version_id,
        status="activated",
        activated_at=now,
        recommendations_applied=0,
    )

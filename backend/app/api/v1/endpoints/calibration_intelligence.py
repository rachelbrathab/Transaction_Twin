"""Calibration Intelligence API endpoints.

Governance-aware advisory calibration analysis with versioned recommendations.
Does NOT modify policies, risk weights, thresholds, or reputation.
Does NOT execute payments or call LLMs.

Ownership: every endpoint requires user_id and validates resource ownership.
State machine: recommendation and version transitions are validated.
Idempotency: repeated activation/review returns existing state safely.
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
from app.models.calibration_recommendation import (
    CalibrationRecommendationRecord,
)
from app.models.calibration_version import CalibrationVersionRecord
from app.models.transaction import Transaction
from app.models.transaction_event import TransactionEvent
from app.services.calibration_intelligence.constants import (
    MAX_WINDOW_DAYS,
)
from app.services.calibration_intelligence.state_machine import (
    can_activate_version,
    validate_recommendation_transition,
)

logger = structlog.get_logger()
router = APIRouter()


# ── Response schemas ───────────────────────────────────────────


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
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    rejection_reason: str | None = None


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
    idempotent: bool = False


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
    idempotent: bool = False


class GenerateRequest(BaseModel):
    """Request to generate a calibration version from verified outcomes."""

    window_days: int = Field(
        default=30,
        ge=1,
        le=MAX_WINDOW_DAYS,
        description="Analysis window in days",
    )


class GenerateResponse(BaseModel):
    """Response for calibration generation."""

    version_id: str
    status: str
    total_samples: int = 0
    eligible_samples: int = 0
    excluded_samples: int = 0
    recommendation_count: int = 0
    generated_at: str = ""
    idempotent: bool = False


class VersionResponse(BaseModel):
    """Single calibration version."""

    id: str
    version_id: str
    source_window_days: int
    total_samples: int
    eligible_samples: int
    excluded_samples: int
    recommendation_count: int
    status: str
    activated_at: str | None = None
    activated_by: str | None = None
    previous_version: str | None = None
    created_at: str = ""


class VersionDetailResponse(BaseModel):
    """Calibration version with its recommendations."""

    version: VersionResponse
    recommendations: list[RecommendationResponse] = Field(
        default_factory=list,
    )


class VersionsListResponse(BaseModel):
    """List of calibration versions."""

    versions: list[VersionResponse] = Field(default_factory=list)
    total: int = 0


# ── Endpoints ──────────────────────────────────────────────────


@router.get(
    "/analytics/calibration/outcomes",
    response_model=OutcomesResponse,
)
async def get_calibration_outcomes(
    db: AsyncSession = Depends(get_db),
    window_days: int = Query(default=30, ge=1, le=MAX_WINDOW_DAYS),
    user_id: uuid.UUID = Query(
        ...,
        description="User ID for ownership validation",
    ),
) -> OutcomesResponse:
    """Get calibration dataset with eligibility information.

    Returns verified outcome samples for calibration analysis.
    Ownership: only returns transactions belonging to the specified user.
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
    user_id: uuid.UUID = Query(
        ...,
        description="User ID for ownership validation",
    ),
) -> RecommendationsListResponse:
    """Get calibration recommendations.

    Returns advisory recommendations from verified outcome analysis.
    Ownership: only returns recommendations belonging to the specified user.
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
    user_id: uuid.UUID = Query(
        ...,
        description="User ID for ownership validation",
    ),
) -> ReviewResponse:
    """Review a calibration recommendation (approve or reject).

    Enforces the recommendation state machine:
    GENERATED → REVIEWED → APPROVED
    GENERATED → REJECTED
    REVIEWED → REJECTED
    """
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
    user_id: uuid.UUID = Query(
        ...,
        description="User ID for ownership validation",
    ),
) -> ActivateResponse:
    """Activate a calibration version.

    Version lifecycle: GENERATED → ACTIVE → SUPERSEDED.
    Must pass confirm=true to activate.
    Previous active version becomes SUPERSEDED.
    Exactly one active version per user.
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


# ── Generate endpoint ───────────────────────────────────────


@router.post(
    "/analytics/calibration/generate",
    response_model=GenerateResponse,
)
async def generate_calibration(
    request: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Query(
        ...,
        description="User ID for ownership validation",
    ),
) -> GenerateResponse:
    """Generate a calibration version from verified outcomes.

    Runs the CalibrationIntelligenceEngine, persists results, and
    returns the generated version. Idempotent for the same user +
    calibration version.
    """
    try:
        return await _generate_calibration_impl(
            db, request, user_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("calibration_generate_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Calibration generation failed",
        ) from e


# ── Version listing endpoints ────────────────────────────────


@router.get(
    "/analytics/calibration/versions",
    response_model=VersionsListResponse,
)
async def list_calibration_versions(
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Query(
        ...,
        description="User ID for ownership validation",
    ),
    status: str | None = Query(default=None),
) -> VersionsListResponse:
    """List calibration versions for the authenticated user."""
    try:
        return await _list_versions_impl(db, user_id, status)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("calibration_versions_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Version listing failed",
        ) from e


@router.get(
    "/analytics/calibration/versions/{version_id}",
    response_model=VersionDetailResponse,
)
async def get_calibration_version(
    version_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Query(
        ...,
        description="User ID for ownership validation",
    ),
) -> VersionDetailResponse:
    """Get a specific calibration version with its recommendations."""
    try:
        return await _get_version_impl(db, version_id, user_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("calibration_version_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Version retrieval failed",
        ) from e


@router.get(
    "/analytics/calibration/recommendations/{recommendation_id}",
    response_model=RecommendationResponse,
)
async def get_calibration_recommendation(
    recommendation_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Query(
        ...,
        description="User ID for ownership validation",
    ),
) -> RecommendationResponse:
    """Get a specific calibration recommendation."""
    try:
        return await _get_recommendation_impl(
            db, recommendation_id, user_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("calibration_rec_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Recommendation retrieval failed",
        ) from e


# ── Implementation ─────────────────────────────────────────────


async def _get_outcomes_impl(
    db: AsyncSession,
    window_days: int,
    user_id: uuid.UUID,
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

    # Query transactions — OWNERSHIP FILTERED
    txn_result = await db.execute(
        select(Transaction)
        .where(
            Transaction.created_at >= window_start,
            Transaction.user_id == user_id,
        )
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
    user_id: uuid.UUID,
) -> RecommendationsListResponse:
    """Get calibration recommendations from the database table."""
    query = (
        select(CalibrationRecommendationRecord)
        .where(CalibrationRecommendationRecord.user_id == user_id)
        .order_by(CalibrationRecommendationRecord.created_at.desc())
        .limit(200)
    )
    result = await db.execute(query)
    records = result.scalars().all()

    recommendations: list[RecommendationResponse] = []
    by_status: dict[str, int] = {}

    for rec in recommendations_from_records(records):
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
    user_id: uuid.UUID,
) -> ReviewResponse:
    """Review (approve/reject) a calibration recommendation."""
    action = request.action.lower().strip()
    if action not in ("approve", "reject"):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid action: {request.action}. "
                f"Must be 'approve' or 'reject'."
            ),
        )

    # 1. Load recommendation
    result = await db.execute(
        select(CalibrationRecommendationRecord).where(
            CalibrationRecommendationRecord.id == uuid.UUID(
                recommendation_id,
            ),
        )
    )
    rec = result.scalar_one_or_none()

    if rec is None:
        raise HTTPException(
            status_code=404,
            detail="Recommendation not found",
        )

    # 2. Validate ownership
    if rec.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Recommendation does not belong to the specified user",
        )

    # 3. Determine target status based on action + current status
    if action == "reject":
        new_status = "rejected"
    elif rec.status == "generated":
        # GENERATED → approve → REVIEWED
        new_status = "reviewed"
    elif rec.status == "reviewed":
        # REVIEWED → approve → APPROVED
        new_status = "approved"
    else:
        new_status = "approved"

    # 4. Validate state transition
    is_valid, error_msg = validate_recommendation_transition(
        rec.status, new_status,
    )
    if not is_valid:
        raise HTTPException(
            status_code=409,
            detail=error_msg or "Invalid state transition",
        )

    # 4. Capture original status BEFORE any mutation
    original_status = rec.status

    # 5. Check idempotency (same state)
    idempotent = rec.status == new_status

    now = datetime.now(UTC)

    if not idempotent:
        # 6. Update governance fields ONLY
        rec.status = new_status
        rec.updated_at = now

        if action == "approve":
            rec.reviewed_at = now
            rec.reviewed_by = user_id
            # Only set approval metadata when transitioning to approved
            if new_status == "approved":
                rec.approved_at = now
                rec.approved_by = user_id
        else:
            rec.reviewed_at = now
            rec.reviewed_by = user_id
            rec.rejection_reason = request.reason

        await db.flush()

        # 7. Create AuditEvent with correct previous_status
        audit_event = AuditEvent(
            entity_type="calibration_recommendation",
            entity_id=rec.id,
            event_type=f"calibration_recommendation_{action}d",
            actor_type="user",
            actor_id=user_id,
            metadata_={
                "recommendation_id": str(rec.id),
                "user_id": str(user_id),
                "previous_status": original_status,
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
        idempotent=idempotent,
    )

    return ReviewResponse(
        recommendation_id=recommendation_id,
        status=rec.status,
        reviewed_at=now.isoformat(),
        idempotent=idempotent,
    )


async def _activate_version_impl(
    db: AsyncSession,
    version_id: str,
    request: ActivateRequest,
    user_id: uuid.UUID,
) -> ActivateResponse:
    """Activate a calibration version with full governance."""
    if not request.confirm:
        raise HTTPException(
            status_code=422,
            detail="Must pass confirm=true to activate a version",
        )

    # 1. Load target version
    result = await db.execute(
        select(CalibrationVersionRecord).where(
            CalibrationVersionRecord.version_id == version_id,
        )
    )
    version = result.scalar_one_or_none()

    if version is None:
        raise HTTPException(
            status_code=404,
            detail="Calibration version not found",
        )

    # 2. Validate ownership
    if version.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Version does not belong to the specified user",
        )

    # 3. Capture original status BEFORE any mutation
    original_status = version.status

    # 4. Idempotency: already active
    if version.status == "active":
        logger.info(
            "calibration_version_activation_idempotent",
            version_id=version_id,
        )
        return ActivateResponse(
            version_id=version_id,
            status="active",
            activated_at=(
                version.activated_at.isoformat()
                if version.activated_at
                else ""
            ),
            previous_version=version.previous_version,
            recommendations_applied=version.recommendation_count,
            idempotent=True,
        )

    # 5. Load all recommendations for this version
    recs_result = await db.execute(
        select(CalibrationRecommendationRecord).where(
            CalibrationRecommendationRecord.calibration_version
            == version_id,
        )
    )
    recommendations = recs_result.scalars().all()

    # 6. Validate activation requirements
    rec_statuses = [r.status for r in recommendations]
    can_activate, error_msg = can_activate_version(
        version.status, rec_statuses,
    )
    if not can_activate:
        raise HTTPException(
            status_code=409,
            detail=error_msg or "Version cannot be activated",
        )

    # 7. Find and supersede current active version
    active_result = await db.execute(
        select(CalibrationVersionRecord).where(
            CalibrationVersionRecord.user_id == user_id,
            CalibrationVersionRecord.status == "active",
            CalibrationVersionRecord.id != version.id,
        )
    )
    previous_active = active_result.scalar_one_or_none()

    now = datetime.now(UTC)

    if previous_active is not None:
        # Supersede previous version
        previous_active.status = "superseded"
        previous_active.updated_at = now
        await db.flush()

        # Audit: superseded
        superseded_audit = AuditEvent(
            entity_type="calibration_version",
            entity_id=previous_active.id,
            event_type="calibration_superseded",
            actor_type="user",
            actor_id=user_id,
            metadata_={
                "version_id": previous_active.version_id,
                "user_id": str(user_id),
                "previous_status": "active",
                "new_status": "superseded",
                "superseded_by": version_id,
            },
        )
        db.add(superseded_audit)

    # 8. Activate target version
    version.status = "active"
    version.activated_at = now
    version.activated_by = user_id
    version.previous_version = (
        previous_active.version_id if previous_active else None
    )
    version.updated_at = now
    await db.flush()

    # 9. Mark activated recommendations
    for rec in recommendations:
        if rec.status == "approved":
            rec.status = "activated"
            rec.activated_at = now
            rec.activated_by = user_id
            rec.updated_at = now
    await db.flush()

    # 10. Audit: activated (use actual original status)
    activated_audit = AuditEvent(
        entity_type="calibration_version",
        entity_id=version.id,
        event_type="calibration_activated",
        actor_type="user",
        actor_id=user_id,
        metadata_={
            "version_id": version_id,
            "user_id": str(user_id),
            "previous_status": original_status,
            "new_status": "active",
            "previous_version": version.previous_version,
        },
    )
    db.add(activated_audit)
    await db.flush()

    logger.info(
        "calibration_version_activated",
        version_id=version_id,
        previous_version=version.previous_version,
    )

    return ActivateResponse(
        version_id=version_id,
        status="active",
        activated_at=now.isoformat(),
        previous_version=version.previous_version,
        recommendations_applied=len([
            r for r in recommendations
            if r.status == "activated"
        ]),
        idempotent=False,
    )


# ── Generate implementation ────────────────────────────────


async def _generate_calibration_impl(
    db: AsyncSession,
    request: GenerateRequest,
    user_id: uuid.UUID,
) -> GenerateResponse:
    """Generate calibration from verified outcomes and persist."""
    from datetime import timedelta

    from app.services.calibration_intelligence.engine import (
        CalibrationIntelligenceEngine,
    )
    from app.services.calibration_intelligence.persistence import (
        persist_calibration_result,
    )

    now = datetime.now(UTC)
    window_start = now - timedelta(days=request.window_days)

    # 1. Query transactions — ownership filtered
    txn_result = await db.execute(
        select(Transaction)
        .where(
            Transaction.created_at >= window_start,
            Transaction.user_id == user_id,
        )
        .order_by(Transaction.created_at.desc())
        .limit(1000)
    )
    txns = txn_result.scalars().all()

    if not txns:
        return GenerateResponse(
            version_id="",
            status="generated",
            generated_at=now.isoformat(),
        )

    txn_ids = [t.id for t in txns]

    # 2. Query decisions
    from app.models.decision import Decision

    dec_result = await db.execute(
        select(Decision).where(Decision.transaction_id.in_(txn_ids))
    )
    decisions = dec_result.scalars().all()

    # 3. Query outcome events
    evt_result = await db.execute(
        select(TransactionEvent).where(
            TransactionEvent.transaction_id.in_(txn_ids),
        )
    )
    events = evt_result.scalars().all()

    # 4. Build record dicts
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

    # 5. Run calibration engine
    engine = CalibrationIntelligenceEngine()
    result = engine.evaluate(
        transaction_records=transaction_records,
        decision_records=decision_records,
        outcome_records=outcome_records,
        window_days=request.window_days,
        user_id=str(user_id),
    )

    # 6. Persist to database
    persistence_result = await persist_calibration_result(
        db, user_id, result,
    )
    version_record = persistence_result.version
    is_new = persistence_result.created

    # 7. Audit event — only for newly created versions
    if is_new:
        audit_event = AuditEvent(
            entity_type="calibration_version",
            entity_id=version_record.id,
            event_type="calibration_generated",
            actor_type="user",
            actor_id=user_id,
            metadata_={
                "version_id": version_record.version_id,
                "user_id": str(user_id),
                "previous_status": None,
                "new_status": "generated",
                "total_samples": version_record.total_samples,
                "eligible_samples": version_record.eligible_samples,
                "recommendation_count": version_record.recommendation_count,
                "window_days": request.window_days,
            },
        )
        db.add(audit_event)
        await db.flush()

    return GenerateResponse(
        version_id=version_record.version_id,
        status=version_record.status,
        total_samples=version_record.total_samples,
        eligible_samples=version_record.eligible_samples,
        excluded_samples=version_record.excluded_samples,
        recommendation_count=version_record.recommendation_count,
        generated_at=version_record.created_at.isoformat()
        if version_record.created_at
        else now.isoformat(),
        idempotent=not is_new,
    )


# ── Version listing implementations ──────────────────────────


async def _list_versions_impl(
    db: AsyncSession,
    user_id: uuid.UUID,
    status_filter: str | None,
) -> VersionsListResponse:
    """List calibration versions for a user."""
    query = (
        select(CalibrationVersionRecord)
        .where(CalibrationVersionRecord.user_id == user_id)
        .order_by(CalibrationVersionRecord.created_at.desc())
        .limit(100)
    )
    result = await db.execute(query)
    records = result.scalars().all()

    versions: list[VersionResponse] = []
    for rec in records:
        if status_filter and rec.status != status_filter:
            continue
        versions.append(VersionResponse(
            id=str(rec.id),
            version_id=rec.version_id,
            source_window_days=rec.source_window_days,
            total_samples=rec.total_samples,
            eligible_samples=rec.eligible_samples,
            excluded_samples=rec.excluded_samples,
            recommendation_count=rec.recommendation_count,
            status=rec.status,
            activated_at=rec.activated_at.isoformat()
            if rec.activated_at
            else None,
            activated_by=str(rec.activated_by)
            if rec.activated_by
            else None,
            previous_version=rec.previous_version,
            created_at=rec.created_at.isoformat()
            if rec.created_at
            else "",
        ))

    return VersionsListResponse(
        versions=versions,
        total=len(versions),
    )


async def _get_version_impl(
    db: AsyncSession,
    version_id: str,
    user_id: uuid.UUID,
) -> VersionDetailResponse:
    """Get a specific version with recommendations."""
    result = await db.execute(
        select(CalibrationVersionRecord).where(
            CalibrationVersionRecord.version_id == version_id,
            CalibrationVersionRecord.user_id == user_id,
        )
    )
    version = result.scalar_one_or_none()

    if version is None:
        raise HTTPException(
            status_code=404,
            detail="Calibration version not found",
        )

    # Load recommendations for this version
    recs_result = await db.execute(
        select(CalibrationRecommendationRecord).where(
            CalibrationRecommendationRecord.calibration_version
            == version_id,
            CalibrationRecommendationRecord.user_id == user_id,
        )
    )
    rec_records = recs_result.scalars().all()

    return VersionDetailResponse(
        version=VersionResponse(
            id=str(version.id),
            version_id=version.version_id,
            source_window_days=version.source_window_days,
            total_samples=version.total_samples,
            eligible_samples=version.eligible_samples,
            excluded_samples=version.excluded_samples,
            recommendation_count=version.recommendation_count,
            status=version.status,
            activated_at=version.activated_at.isoformat()
            if version.activated_at
            else None,
            activated_by=str(version.activated_by)
            if version.activated_by
            else None,
            previous_version=version.previous_version,
            created_at=version.created_at.isoformat()
            if version.created_at
            else "",
        ),
        recommendations=recommendations_from_records(
            list(rec_records),
        ),
    )


async def _get_recommendation_impl(
    db: AsyncSession,
    recommendation_id: str,
    user_id: uuid.UUID,
) -> RecommendationResponse:
    """Get a specific recommendation."""
    result = await db.execute(
        select(CalibrationRecommendationRecord).where(
            CalibrationRecommendationRecord.id == uuid.UUID(
                recommendation_id,
            ),
            CalibrationRecommendationRecord.user_id == user_id,
        )
    )
    rec = result.scalar_one_or_none()

    if rec is None:
        raise HTTPException(
            status_code=404,
            detail="Recommendation not found",
        )

    return recommendations_from_records([rec])[0]


# ── Helpers ────────────────────────────────────────────────────


def recommendations_from_records(
    records: list[CalibrationRecommendationRecord],
) -> list[RecommendationResponse]:
    """Convert database records to response models."""
    results: list[RecommendationResponse] = []
    for rec in records:
        results.append(RecommendationResponse(
            recommendation_id=str(rec.id),
            recommendation_type=rec.recommendation_type,
            engine=rec.engine,
            parameter=rec.parameter,
            current_value=rec.current_value,
            proposed_value=rec.proposed_value,
            evidence=rec.evidence or {},
            sample_count=rec.sample_count,
            data_sufficiency=rec.confidence,
            rationale=rec.rationale,
            severity=rec.severity,
            generated_at=rec.created_at.isoformat()
            if rec.created_at
            else "",
            calibration_version=rec.calibration_version,
            status=rec.status,
            reviewed_at=rec.reviewed_at.isoformat()
            if rec.reviewed_at
            else None,
            reviewed_by=str(rec.reviewed_by)
            if rec.reviewed_by
            else None,
            approved_at=rec.approved_at.isoformat()
            if rec.approved_at
            else None,
            approved_by=str(rec.approved_by)
            if rec.approved_by
            else None,
            rejection_reason=rec.rejection_reason,
        ))
    return results

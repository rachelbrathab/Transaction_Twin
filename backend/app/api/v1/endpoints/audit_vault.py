"""Audit Vault API endpoint.

GET /api/v1/audit/events — list audit events for the authenticated user.
GET /api/v1/audit/events/{event_id} — get audit event detail.

Read-only. Ownership-scoped via actor_id.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.identity import get_current_user
from app.models.audit_event import AuditEvent
from app.models.user import User

logger = structlog.get_logger()
router = APIRouter()


# ── Response schemas ───────────────────────────────────────────


class AuditEventItem(BaseModel):
    """Summary of an audit event."""

    id: str
    entity_type: str
    entity_id: str
    event_type: str
    actor_type: str | None = None
    actor_id: str | None = None
    metadata: dict | None = None
    created_at: str


class AuditEventListResponse(BaseModel):
    """Paginated list of audit events."""

    events: list[AuditEventItem] = Field(default_factory=list)
    total: int = 0


class AuditEventDetailResponse(BaseModel):
    """Full audit event detail."""

    id: str
    entity_type: str
    entity_id: str
    event_type: str
    actor_type: str | None = None
    actor_id: str | None = None
    metadata: dict | None = None
    previous_hash: str | None = None
    current_hash: str | None = None
    created_at: str


# ── Endpoints ──────────────────────────────────────────────────


@router.get("/audit/events", response_model=AuditEventListResponse)
async def list_audit_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    entity_type: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> AuditEventListResponse:
    """List audit events where the user is the actor.

    Ownership-scoped: only returns events where actor_id matches the user.
    """
    try:
        return await _list_events_impl(
            user_id=current_user.id,
            entity_type=entity_type,
            event_type=event_type,
            limit=limit,
            offset=offset,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("audit_list_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to list audit events") from e


async def _list_events_impl(
    user_id: uuid.UUID,
    entity_type: str | None,
    event_type: str | None,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> AuditEventListResponse:
    base_query = AuditEvent.actor_id == user_id
    count_query = select(func.count()).select_from(AuditEvent).where(base_query)
    query = select(AuditEvent).where(base_query)

    if entity_type:
        count_query = count_query.where(AuditEvent.entity_type == entity_type)
        query = query.where(AuditEvent.entity_type == entity_type)
    if event_type:
        count_query = count_query.where(AuditEvent.event_type == event_type)
        query = query.where(AuditEvent.event_type == event_type)

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    result = await db.execute(
        query.order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset),
    )
    events = result.scalars().all()

    return AuditEventListResponse(
        events=[_to_item(e) for e in events],
        total=total,
    )


@router.get("/audit/events/{event_id}", response_model=AuditEventDetailResponse)
async def get_audit_event(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuditEventDetailResponse:
    """Get a specific audit event."""
    result = await db.execute(
        select(AuditEvent).where(AuditEvent.id == event_id),
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found")
    if event.actor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return AuditEventDetailResponse(
        id=str(event.id),
        entity_type=event.entity_type,
        entity_id=str(event.entity_id),
        event_type=event.event_type,
        actor_type=event.actor_type,
        actor_id=str(event.actor_id) if event.actor_id else None,
        metadata=event.metadata_,
        previous_hash=event.previous_hash,
        current_hash=event.current_hash,
        created_at=event.created_at.isoformat(),
    )


# ── Helpers ────────────────────────────────────────────────────


def _to_item(e: AuditEvent) -> AuditEventItem:
    return AuditEventItem(
        id=str(e.id),
        entity_type=e.entity_type,
        entity_id=str(e.entity_id),
        event_type=e.event_type,
        actor_type=e.actor_type,
        actor_id=str(e.actor_id) if e.actor_id else None,
        metadata=e.metadata_,
        created_at=e.created_at.isoformat(),
    )

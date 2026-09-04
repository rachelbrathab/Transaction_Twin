"""Policy CRUD API endpoints.

Full create/read/update/delete for policies.
Ownership-scoped. Authenticated.
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
from app.core.identity import get_current_user
from app.models.policy import Policy
from app.models.user import User

logger = structlog.get_logger()
router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────


class PolicyCreate(BaseModel):
    """Request to create a policy."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    rules: dict | None = None
    scope: dict | None = None


class PolicyUpdate(BaseModel):
    """Request to update a policy."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = None
    rules: dict | None = None
    scope: dict | None = None


class PolicyResponse(BaseModel):
    """Policy response."""

    id: str
    user_id: str
    name: str
    description: str | None
    status: str
    version: int
    rules: dict | None
    scope: dict | None
    effective_from: str | None
    effective_until: str | None
    created_at: str
    updated_at: str


class PolicyListResponse(BaseModel):
    """List of policies."""

    policies: list[PolicyResponse] = Field(default_factory=list)
    total: int = 0


# ── Endpoints ──────────────────────────────────────────────────


@router.post("/policies", response_model=PolicyResponse, status_code=201)
async def create_policy(
    request: PolicyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    """Create a new policy for the authenticated user."""
    try:
        return await _create_policy_impl(request, current_user.id, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("policy_create_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create policy") from e


async def _create_policy_impl(
    request: PolicyCreate,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> PolicyResponse:
    now = datetime.now(UTC)
    policy = Policy(
        user_id=user_id,
        name=request.name,
        description=request.description,
        rules=request.rules,
        scope=request.scope,
        status="draft",
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(policy)
    await db.flush()

    logger.info("policy_created", policy_id=str(policy.id), user_id=str(user_id))
    return _to_response(policy)


@router.get("/policies", response_model=PolicyListResponse)
async def list_policies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PolicyListResponse:
    """List policies for the authenticated user."""
    try:
        return await _list_policies_impl(
            user_id=current_user.id, status=status,
            limit=limit, offset=offset, db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("policy_list_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to list policies") from e


async def _list_policies_impl(
    user_id: uuid.UUID,
    status: str | None,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> PolicyListResponse:
    from sqlalchemy import func

    query = select(Policy).where(Policy.user_id == user_id)
    count_query = select(func.count()).select_from(Policy).where(Policy.user_id == user_id)

    if status:
        query = query.where(Policy.status == status)
        count_query = count_query.where(Policy.status == status)

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    result = await db.execute(
        query.order_by(Policy.created_at.desc()).limit(limit).offset(offset),
    )
    policies = result.scalars().all()

    return PolicyListResponse(
        policies=[_to_response(p) for p in policies],
        total=total,
    )


@router.get("/policies/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    """Get a specific policy."""
    result = await db.execute(
        select(Policy).where(Policy.id == policy_id),
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    if policy.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return _to_response(policy)


@router.put("/policies/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: uuid.UUID,
    request: PolicyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    """Update a policy."""
    result = await db.execute(
        select(Policy).where(Policy.id == policy_id),
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    if policy.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if request.name is not None:
        policy.name = request.name
    if request.description is not None:
        policy.description = request.description
    if request.status is not None:
        policy.status = request.status
    if request.rules is not None:
        policy.rules = request.rules
    if request.scope is not None:
        policy.scope = request.scope

    policy.updated_at = datetime.now(UTC)
    policy.version += 1
    await db.flush()

    logger.info("policy_updated", policy_id=str(policy_id))
    return _to_response(policy)


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a policy."""
    result = await db.execute(
        select(Policy).where(Policy.id == policy_id),
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    if policy.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    await db.delete(policy)
    await db.flush()
    logger.info("policy_deleted", policy_id=str(policy_id))


# ── Helper ─────────────────────────────────────────────────────


def _to_response(p: Policy) -> PolicyResponse:
    return PolicyResponse(
        id=str(p.id),
        user_id=str(p.user_id),
        name=p.name,
        description=p.description,
        status=p.status,
        version=p.version,
        rules=p.rules,
        scope=p.scope,
        effective_from=p.effective_from.isoformat() if p.effective_from else None,
        effective_until=p.effective_until.isoformat() if p.effective_until else None,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
    )

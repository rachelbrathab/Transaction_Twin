"""Server-side identity abstraction.

Provides `get_current_user` — a FastAPI dependency that resolves the
authenticated user from a TRUSTED server-side source.

Production:
    A reverse proxy (nginx auth_request, Cloudflare Access, etc.)
    authenticates the caller and sets the ``X-Forwarded-User-Id``
    header BEFORE the request reaches this application.  The reverse
    proxy MUST strip any client-supplied value for this header.

Development (APP_ENV=development):
    The header is read directly from the request.  This is convenient
    for local development but MUST NOT be used in production — a
    client-controlled header is not authentication.

Never accept user_id from query parameters, request bodies, or any
other client-controllable field as the identity source.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User

logger = structlog.get_logger()

settings = get_settings()

# Header name used by the reverse proxy to communicate the authenticated
# user identity.  In production this header is set ONLY by the trusted
# reverse proxy; any client-provided value is stripped.
AUTH_IDENTITY_HEADER = "X-Forwarded-User-Id"


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_forwarded_user_id: str | None = Header(
        default=None,
        description=(
            "Server-set header identifying the authenticated user. "
            "In production this is set exclusively by the reverse proxy."
        ),
    ),
) -> User:
    """Resolve the authenticated user from a trusted server-side source.

    Resolution order:
        1. ``X-Forwarded-User-Id`` header (set by reverse proxy in prod,
           or read directly in development mode).
        2. If the header is missing or empty → HTTP 401.
        3. If the value is not a valid UUID → HTTP 401.
        4. If no matching user exists in the database → HTTP 401.

    Returns the ORM ``User`` object so callers can use ``user.id``
    without any additional lookup.

    This dependency is intentionally independent from calibration
    business logic — it can be reused by any endpoint that requires
    an authenticated caller.
    """

    # --- Resolve identity value ---
    identity_value: str | None = x_forwarded_user_id

    # In development mode, also check a cookie for convenience with
    # the local Next.js dev server.  This is dev-only convenience and
    # MUST NOT be relied upon in production.
    if not identity_value and settings.is_development:
        identity_value = request.cookies.get("dev_user_id")

    # --- Validate presence ---
    if not identity_value:
        logger.warning(
            "identity_missing",
            path=request.url.path,
            method=request.method,
        )
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    # --- Validate format ---
    try:
        user_uuid = uuid.UUID(identity_value)
    except ValueError:
        logger.warning(
            "identity_invalid_format",
            path=request.url.path,
            method=request.method,
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid identity",
        )

    # --- Resolve user in database ---
    result = await db.execute(
        sa_select(User).where(User.id == user_uuid)
    )
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning(
            "identity_user_not_found",
            user_id=str(user_uuid),
            path=request.url.path,
            method=request.method,
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid identity",
        )

    return user

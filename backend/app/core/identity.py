"""Server-side identity abstraction.

Provides `get_current_user` — a FastAPI dependency that resolves the
authenticated user from a validated JWT bearer token.

Authentication flow:
    1. Client sends ``Authorization: Bearer <jwt-token>`` header.
    2. The JWT is validated (signature, expiry, format).
    3. The ``sub`` claim is extracted as the user UUID.
    4. The user is loaded from the database.
    5. The user's ``status`` must be ``active``.
    6. If any step fails → HTTP 401.

Never accept user_id from query parameters, request bodies, cookies,
or any other client-controllable field as the identity source.
"""

from __future__ import annotations

import structlog
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import decode_access_token
from app.core.database import get_db
from app.models.user import User

logger = structlog.get_logger()


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    """Resolve the authenticated user from a validated JWT bearer token.

    Resolution order:
        1. ``Authorization: Bearer <token>`` header.
        2. If the header is missing or malformed → HTTP 401.
        3. If the token is expired or invalid → HTTP 401.
        4. If the user does not exist → HTTP 401.
        5. If the user is not active → HTTP 401.

    Returns the ORM ``User`` object so callers can use ``user.id``
    without any additional lookup.

    This dependency is intentionally independent from calibration
    business logic — it can be reused by any endpoint that requires
    an authenticated caller.
    """

    # --- Extract token from Authorization header ---
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning(
            "identity_missing",
        )
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    token = authorization[7:]  # Strip "Bearer " prefix

    # --- Validate JWT ---
    user_uuid = decode_access_token(token)
    if user_uuid is None:
        logger.warning("identity_invalid_token")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
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
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid identity",
        )

    # --- Check user status ---
    if user.status != "active":
        logger.warning(
            "identity_user_inactive",
            user_id=str(user.id),
            status=user.status,
        )
        raise HTTPException(
            status_code=401,
            detail="Account is not active",
        )

    return user

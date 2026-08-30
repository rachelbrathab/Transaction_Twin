"""Authentication endpoints.

POST /auth/signup — create a new user account.
POST /auth/login — authenticate and receive a JWT token.
POST /auth/refresh — refresh an expired access token.

Does NOT call LLMs. Does NOT execute payments.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    hash_password,
    validate_refresh_token,
    verify_password,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import get_client_ip, get_rate_limiter
from app.models.refresh_token import RefreshTokenRecord
from app.models.user import User

logger = structlog.get_logger()
router = APIRouter()
settings = get_settings()

# Dummy bcrypt hash used for timing-side-channel mitigation.
# When a nonexistent user attempts login, we still run bcrypt against
# this dummy hash so the response time is constant.
_DUMMY_BCRYPT_HASH = hash_password("dummy-password-for-timing-constant-9xK2mP")

# Rate limit configurations
_LOGIN_RATE_LIMIT = 5  # attempts per minute per IP
_LOGIN_RATE_WINDOW = 60  # seconds
_SIGNUP_RATE_LIMIT = 3  # accounts per minute per IP
_SIGNUP_RATE_WINDOW = 60  # seconds


# ── Request / Response schemas ─────────────────────────────────────


class SignupRequest(BaseModel):
    """Request body for user registration."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=255)


class LoginRequest(BaseModel):
    """Request body for user login."""

    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    """Response for successful authentication."""

    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    display_name: str


class RefreshRequest(BaseModel):
    """Request body for token refresh."""

    refresh_token: str | None = Field(
        default=None,
        description="Refresh token. If not provided, reads from cookie.",
    )


# ── Cookie helpers ──────────────────────────────────────────────────


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Set the refresh token as an HttpOnly secure cookie."""
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        path="/auth/refresh",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie."""
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/auth/refresh",
    )


# ── Endpoints ───────────────────────────────────────────────────────


@router.post("/signup", response_model=AuthResponse)
async def signup(
    request: SignupRequest,
    req: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Create a new user account and return a JWT token.

    Returns 409 if the email is already registered.
    Returns 429 if rate limit exceeded.
    """
    # Rate limit check
    client_ip = get_client_ip(req)
    await get_rate_limiter().check(f"signup:{client_ip}", _SIGNUP_RATE_LIMIT, _SIGNUP_RATE_WINDOW)

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == request.email))
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Email already registered",
        )

    # Create user
    user = User(
        email=request.email,
        password_hash=hash_password(request.password),
        display_name=request.display_name,
        status="active",
    )
    db.add(user)
    await db.flush()

    token = create_access_token(user.id)
    refresh = await create_refresh_token(db, user.id)
    _set_refresh_cookie(response, refresh)

    logger.info("user_signup", user_id=str(user.id), email=request.email)

    return AuthResponse(
        access_token=token,
        user_id=user.id,
        display_name=user.display_name,
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    request: LoginRequest,
    req: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Authenticate with email and password, return a JWT token.

    Returns 401 for invalid credentials or inactive accounts.
    Returns 429 if rate limit exceeded.

    Timing-hardened: bcrypt verification runs even for nonexistent users
    to prevent user enumeration through response time analysis.
    """
    # Rate limit check
    client_ip = get_client_ip(req)
    await get_rate_limiter().check(f"login:{client_ip}", _LOGIN_RATE_LIMIT, _LOGIN_RATE_WINDOW)

    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    # Timing-hardened: always run bcrypt, even for nonexistent users.
    # This ensures the response time is constant regardless of whether
    # the user exists, preventing timing-based user enumeration.
    if user is not None and user.password_hash is not None:
        # Real user — verify actual password
        password_valid = verify_password(request.password, user.password_hash)
    else:
        # Nonexistent user — verify against dummy hash (constant time)
        password_valid = verify_password(request.password, _DUMMY_BCRYPT_HASH)

    if user is None or user.password_hash is None or not password_valid:
        logger.warning("login_failed", email=request.email)
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    if user.status != "active":
        logger.warning("login_failed_inactive", user_id=str(user.id))
        raise HTTPException(
            status_code=401,
            detail="Account is not active",
        )

    token = create_access_token(user.id)
    refresh = await create_refresh_token(db, user.id)
    _set_refresh_cookie(response, refresh)

    logger.info("user_login", user_id=str(user.id))

    return AuthResponse(
        access_token=token,
        user_id=user.id,
        display_name=user.display_name,
    )


@router.post("/refresh")
async def refresh_token(
    req: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Refresh an expired access token using a refresh token.

    The refresh token is read from the HttpOnly cookie or request body.
    Returns a new access token and rotates the refresh token.

    Returns 401 if the refresh token is invalid, expired, or revoked.
    """
    # Extract refresh token from cookie or body
    refresh_token_value = req.cookies.get("refresh_token")
    if refresh_token_value is None:
        body = await _safe_parse_body(req)
        if body and body.get("refresh_token"):
            refresh_token_value = body["refresh_token"]

    if not refresh_token_value:
        raise HTTPException(
            status_code=401,
            detail="Refresh token required",
        )

    # Decode and validate the refresh token
    token_data = await validate_refresh_token(db, refresh_token_value)
    if token_data is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired refresh token",
        )

    user_id, token_id = token_data

    # Look up the refresh token record to rotate it
    result = await db.execute(
        select(RefreshTokenRecord).where(
            RefreshTokenRecord.id == token_id,
            RefreshTokenRecord.user_id == user_id,
        )
    )
    db_token = result.scalar_one_or_none()

    if db_token is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired refresh token",
        )

    # Rotate: revoke old token, issue new one
    from datetime import UTC, datetime

    db_token.revoked_at = datetime.now(UTC)
    await db.flush()

    # Issue new tokens
    new_access = create_access_token(user_id)
    new_refresh = await create_refresh_token(db, user_id)
    _set_refresh_cookie(response, new_refresh)

    logger.info("token_refreshed", user_id=str(user_id))

    return {
        "access_token": new_access,
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout(
    req: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Logout: revoke refresh token and clear cookie."""
    refresh_token_value = req.cookies.get("refresh_token")
    if refresh_token_value:
        token_data = await validate_refresh_token(db, refresh_token_value)
        if token_data:
            user_id, token_id = token_data
            result = await db.execute(
                select(RefreshTokenRecord).where(
                    RefreshTokenRecord.id == token_id,
                )
            )
            db_token = result.scalar_one_or_none()
            if db_token and db_token.revoked_at is None:
                from datetime import UTC, datetime

                db_token.revoked_at = datetime.now(UTC)
                await db.flush()

    _clear_refresh_cookie(response)
    return {"detail": "Logged out"}


async def _safe_parse_body(req: Request) -> dict | None:
    """Safely parse request body as JSON, returning None on failure."""
    try:
        body = await req.json()
        if isinstance(body, dict):
            return body
    except Exception:
        pass
    return None


async def _revoke_all_user_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Revoke all active refresh tokens for a user (security measure)."""
    from datetime import UTC, datetime

    result = await db.execute(
        select(RefreshTokenRecord).where(
            RefreshTokenRecord.user_id == user_id,
            RefreshTokenRecord.revoked_at.is_(None),
        )
    )
    for token in result.scalars().all():
        token.revoked_at = datetime.now(UTC)
    await db.flush()

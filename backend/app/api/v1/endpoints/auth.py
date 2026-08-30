"""Authentication endpoints.

POST /api/v1/auth/signup — create a new user account.
POST /api/v1/auth/login — authenticate and receive a JWT token.

Does NOT call LLMs. Does NOT execute payments.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, hash_password, verify_password
from app.core.database import get_db
from app.models.user import User

logger = structlog.get_logger()
router = APIRouter()


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


# ── Endpoints ───────────────────────────────────────────────────────


@router.post("/signup", response_model=AuthResponse)
async def signup(request: SignupRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    """Create a new user account and return a JWT token.

    Returns 409 if the email is already registered.
    """
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
    logger.info("user_signup", user_id=str(user.id), email=request.email)

    return AuthResponse(
        access_token=token,
        user_id=user.id,
        display_name=user.display_name,
    )


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    """Authenticate with email and password, return a JWT token.

    Returns 401 for invalid credentials or inactive accounts.
    """
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None:
        logger.warning("login_failed_user_not_found", email=request.email)
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    if not verify_password(request.password, user.password_hash):
        logger.warning("login_failed_bad_password", user_id=str(user.id))
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
    logger.info("user_login", user_id=str(user.id))

    return AuthResponse(
        access_token=token,
        user_id=user.id,
        display_name=user.display_name,
    )

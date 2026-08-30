"""JWT authentication service.

Creates and validates JSON Web Tokens for user authentication.
Tokens contain the user's UUID and are signed with a server-side secret.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import structlog
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def create_access_token(user_id: uuid.UUID) -> str:
    """Create a signed JWT access token for the given user.

    Token payload:
        sub: user UUID as string
        exp: expiration timestamp
        iat: issued-at timestamp
    """
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": now,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token


def decode_access_token(token: str) -> uuid.UUID | None:
    """Decode and validate a JWT access token.

    Returns the user UUID if valid, None if expired/invalid/malformed.
    Never raises — all errors are swallowed and return None.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id_str = payload.get("sub")
        if user_id_str is None:
            return None
        return uuid.UUID(user_id_str)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, ValueError):
        return None


# ── Refresh Token Functions ────────────────────────────────────────


def _hash_token(token: str) -> str:
    """Create a SHA-256 hash of a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_refresh_token(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Create a new refresh token, persist it, and return the raw token.

    The raw token is returned to be set as an HttpOnly cookie.
    Only the hash is stored in the database.
    """
    from app.models.refresh_token import RefreshTokenRecord

    # 128 bits of entropy from two UUID4s
    raw_token = str(uuid.uuid4()) + ":" + str(uuid.uuid4())
    token_hash = _hash_token(raw_token)

    db_token = RefreshTokenRecord(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC)
        + timedelta(days=settings.jwt_refresh_token_expire_days),
    )
    db.add(db_token)
    await db.flush()

    return raw_token


async def validate_refresh_token(
    db: AsyncSession, raw_token: str
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Validate a refresh token and return (user_id, token_record_id).

    Looks up the token by hash. Returns None if not found, expired, or revoked.
    """
    from app.models.refresh_token import RefreshTokenRecord

    token_hash = _hash_token(raw_token)
    result = await db.execute(
        sa_select(RefreshTokenRecord).where(
            RefreshTokenRecord.token_hash == token_hash,
        )
    )
    db_token = result.scalar_one_or_none()

    if db_token is None:
        return None

    if db_token.revoked_at is not None:
        return None

    # Handle both naive (SQLite) and aware (PostgreSQL) datetimes
    now = datetime.now(UTC)
    expires = db_token.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < now:
        return None

    return (db_token.user_id, db_token.id)

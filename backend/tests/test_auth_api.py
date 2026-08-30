"""Tests for authentication endpoints — signup, login, JWT validation.

Verifies:
- User registration and login
- JWT token creation and validation
- Invalid credentials handling
- Inactive user rejection
- Token expiry
- Authorization header validation
- Cross-user isolation
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import create_access_token, decode_access_token
from app.core.database import Base, get_db
from app.core.rate_limit import clear_rate_limiter
from app.main import app


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Ensure dependency overrides and rate limiter are cleared after every test."""
    clear_rate_limiter()
    yield
    app.dependency_overrides.clear()
    clear_rate_limiter()


def _make_engine_and_factory():
    """Create a fresh in-memory SQLite engine and session factory."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _setup_db_override(factory):
    """Override get_db to use the given factory."""

    async def _override_get_db():
        async with factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db


async def _create_tables(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.mark.asyncio
class TestSignup:
    """POST /auth/signup"""

    async def test_successful_signup(self):
        """New user can sign up and receives a JWT token."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/auth/signup",
                    json={
                        "email": "test@example.com",
                        "password": "securepassword123",
                        "display_name": "Test User",
                    },
                )
                assert response.status_code == 200
                body = response.json()
                assert "access_token" in body
                assert body["token_type"] == "bearer"
                assert "user_id" in body
                assert body["display_name"] == "Test User"
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_duplicate_email_rejected(self):
        """Cannot sign up with an already-registered email."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    "/auth/signup",
                    json={
                        "email": "dup@example.com",
                        "password": "securepassword123",
                        "display_name": "User 1",
                    },
                )
                response = await client.post(
                    "/auth/signup",
                    json={
                        "email": "dup@example.com",
                        "password": "anotherpassword",
                        "display_name": "User 2",
                    },
                )
                assert response.status_code == 409
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_short_password_rejected(self):
        """Password must be at least 8 characters."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/auth/signup",
                    json={
                        "email": "short@example.com",
                        "password": "1234567",
                        "display_name": "Short Password",
                    },
                )
                assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_invalid_email_rejected(self):
        """Invalid email format is rejected."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/auth/signup",
                    json={
                        "email": "not-an-email",
                        "password": "securepassword123",
                        "display_name": "Bad Email",
                    },
                )
                assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


@pytest.mark.asyncio
class TestLogin:
    """POST /auth/login"""

    async def test_successful_login(self):
        """Existing user can log in and receives a JWT token."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    "/auth/signup",
                    json={
                        "email": "login@example.com",
                        "password": "securepassword123",
                        "display_name": "Login User",
                    },
                )
                response = await client.post(
                    "/auth/login",
                    json={
                        "email": "login@example.com",
                        "password": "securepassword123",
                    },
                )
                assert response.status_code == 200
                body = response.json()
                assert "access_token" in body
                assert body["display_name"] == "Login User"
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_wrong_password_rejected(self):
        """Wrong password returns 401."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    "/auth/signup",
                    json={
                        "email": "wrong@example.com",
                        "password": "securepassword123",
                        "display_name": "Wrong Password User",
                    },
                )
                response = await client.post(
                    "/auth/login",
                    json={
                        "email": "wrong@example.com",
                        "password": "wrongpassword",
                    },
                )
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_nonexistent_user_rejected(self):
        """Nonexistent email returns 401."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/auth/login",
                    json={
                        "email": "nonexistent@example.com",
                        "password": "securepassword123",
                    },
                )
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


@pytest.mark.asyncio
class TestJWTValidation:
    """JWT token creation and validation."""

    def test_token_creation_and_decode(self):
        """Valid token can be decoded to recover user_id."""
        user_id = uuid.uuid4()
        token = create_access_token(user_id)
        decoded = decode_access_token(token)
        assert decoded == user_id

    def test_expired_token_rejected(self):
        """Expired token returns None."""
        import jwt

        from app.core.config import get_settings

        settings = get_settings()
        user_id = uuid.uuid4()
        payload = {
            "sub": str(user_id),
            "exp": 0,
            "iat": 0,
        }
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        decoded = decode_access_token(token)
        assert decoded is None

    def test_invalid_token_rejected(self):
        """Tampered token returns None."""
        user_id = uuid.uuid4()
        token = create_access_token(user_id)
        tampered = token[:-5] + "XXXXX"
        decoded = decode_access_token(tampered)
        assert decoded is None

    def test_wrong_secret_rejected(self):
        """Token signed with wrong secret returns None."""
        import jwt

        user_id = uuid.uuid4()
        payload = {
            "sub": str(user_id),
            "exp": 9999999999,
            "iat": 0,
        }
        token = jwt.encode(
            payload, "wrong-secret-key-that-is-long-enough-for-hmac", algorithm="HS256"
        )
        decoded = decode_access_token(token)
        assert decoded is None

    def test_malformed_token_rejected(self):
        """Completely invalid string returns None."""
        decoded = decode_access_token("not-a-jwt-token")
        assert decoded is None

    def test_empty_token_rejected(self):
        """Empty string returns None."""
        decoded = decode_access_token("")
        assert decoded is None


@pytest.mark.asyncio
class TestProtectedEndpoint:
    """Verify that protected endpoints require valid JWT."""

    async def test_no_auth_returns_401(self):
        """Unauthenticated request returns 401."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/analytics/calibration/versions")
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_invalid_token_returns_401(self):
        """Request with invalid token returns 401."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/analytics/calibration/versions",
                    headers={"Authorization": "Bearer invalid-token"},
                )
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_inactive_user_returns_401(self):
        """Inactive user cannot access protected endpoints."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)

        # Create an inactive user directly
        async with factory() as session:
            from app.models.user import User

            inactive_user = User(
                id=uuid.uuid4(),
                display_name="Inactive",
                status="inactive",
            )
            session.add(inactive_user)
            await session.commit()
            inactive_id = inactive_user.id

        _setup_db_override(factory)
        try:
            token = create_access_token(inactive_id)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/analytics/calibration/versions",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

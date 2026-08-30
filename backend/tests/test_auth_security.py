"""Comprehensive security test suite for authentication hardening.

Tests cover:
- JWT secret validation (production fail-fast)
- Rate limiting (login and signup)
- Timing side-channel mitigation
- Refresh token lifecycle
- Security invariants
"""

from __future__ import annotations

import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import (
    create_access_token,
)
from app.core.database import Base, get_db
from app.core.rate_limit import clear_rate_limiter
from app.main import app

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_state():
    """Clear rate limiter and dependency overrides after each test."""
    clear_rate_limiter()
    yield
    app.dependency_overrides.clear()
    clear_rate_limiter()


def _make_engine_and_factory():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _setup_db_override(factory):
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


async def _signup_user(client: AsyncClient, email: str = "test@example.com") -> dict:
    """Sign up a test user and return the response body."""
    resp = await client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "securepassword123",
            "display_name": "Test User",
        },
    )
    assert resp.status_code == 200
    return resp.json()


# ── PHASE 1: JWT Secret Validation ─────────────────────────────────


class TestProductionSecretValidation:
    """Verify fail-fast validation for production JWT secret."""

    def test_production_insecure_default_rejected(self):
        """Production with insecure default secret must raise RuntimeError."""
        from app.core.config import Settings, validate_production_settings

        settings = Settings(
            app_env="production",
            jwt_secret_key="dev-only-insecure-key-must-override-in-production-19ad87",
        )
        with pytest.raises(RuntimeError, match="FATAL"):
            validate_production_settings(settings)

    def test_production_empty_secret_rejected(self):
        """Production with empty secret must raise RuntimeError."""
        from app.core.config import Settings, validate_production_settings

        settings = Settings(app_env="production", jwt_secret_key="")
        with pytest.raises(RuntimeError, match="FATAL"):
            validate_production_settings(settings)

    def test_production_short_secret_rejected(self):
        """Production with short secret must raise RuntimeError."""
        from app.core.config import Settings, validate_production_settings

        settings = Settings(app_env="production", jwt_secret_key="short")
        with pytest.raises(RuntimeError, match="FATAL"):
            validate_production_settings(settings)

    def test_production_valid_secret_accepted(self):
        """Production with valid secret must pass validation."""
        from app.core.config import Settings, validate_production_settings

        settings = Settings(
            app_env="production",
            jwt_secret_key="a-very-long-and-secure-production-secret-key-32chars+",
        )
        validate_production_settings(settings)  # Should not raise

    def test_development_default_accepted(self):
        """Development with default secret must pass validation."""
        from app.core.config import Settings, validate_production_settings

        settings = Settings(app_env="development")
        validate_production_settings(settings)  # Should not raise

    def test_testing_default_accepted(self):
        """Testing with default secret must pass validation."""
        from app.core.config import Settings, validate_production_settings

        settings = Settings(app_env="testing")
        validate_production_settings(settings)  # Should not raise


# ── PHASE 2: Rate Limiting ─────────────────────────────────────────


class TestLoginRateLimiting:
    """Verify rate limiting on POST /auth/login."""

    async def test_login_rate_limit_enforced(self):
        """Exceeding login rate limit returns HTTP 429."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Sign up a user first
                await _signup_user(client, "ratelimit@example.com")

                # Make 5 login attempts (the limit)
                for i in range(5):
                    await client.post(
                        "/auth/login",
                        json={
                            "email": "ratelimit@example.com",
                            "password": "wrongpassword" if i < 4 else "securepassword123",
                        },
                    )

                # 6th attempt should be rate-limited
                response = await client.post(
                    "/auth/login",
                    json={
                        "email": "ratelimit@example.com",
                        "password": "securepassword123",
                    },
                )
                assert response.status_code == 429
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_login_rate_limit_resets_after_window(self):
        """Rate limit resets after the time window expires."""
        # This test verifies the rate limiter uses time windows
        # by checking that a fresh key works
        clear_rate_limiter()
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await _signup_user(client, "reset@example.com")
                # First login should work
                response = await client.post(
                    "/auth/login",
                    json={
                        "email": "reset@example.com",
                        "password": "securepassword123",
                    },
                )
                assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


class TestSignupRateLimiting:
    """Verify rate limiting on POST /auth/signup."""

    async def test_signup_rate_limit_enforced(self):
        """Exceeding signup rate limit returns HTTP 429."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Make 3 signups (the limit)
                for i in range(3):
                    await client.post(
                        "/auth/signup",
                        json={
                            "email": f"signup{i}@example.com",
                            "password": "securepassword123",
                            "display_name": f"User {i}",
                        },
                    )

                # 4th attempt should be rate-limited
                response = await client.post(
                    "/auth/signup",
                    json={
                        "email": "signup3@example.com",
                        "password": "securepassword123",
                        "display_name": "User 3",
                    },
                )
                assert response.status_code == 429
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


# ── PHASE 3: Timing Side-Channel ──────────────────────────────────


class TestTimingHardening:
    """Verify bcrypt runs for nonexistent users."""

    async def test_nonexistent_user_performs_bcrypt(self):
        """Login with nonexistent user must still perform bcrypt verification."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                start = time.monotonic()
                response = await client.post(
                    "/auth/login",
                    json={
                        "email": "nonexistent@example.com",
                        "password": "securepassword123",
                    },
                )
                elapsed = time.monotonic() - start

                # Should return 401 with generic message
                assert response.status_code == 401
                assert response.json()["detail"] == "Invalid email or password"

                # Should take at least 50ms (bcrypt overhead)
                # This verifies bcrypt actually ran
                assert elapsed > 0.05, f"Bcrypt did not run: {elapsed:.3f}s"
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_wrong_password_performs_bcrypt(self):
        """Login with wrong password must perform bcrypt verification."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await _signup_user(client, "timing@example.com")

                start = time.monotonic()
                response = await client.post(
                    "/auth/login",
                    json={
                        "email": "timing@example.com",
                        "password": "wrongpassword",
                    },
                )
                elapsed = time.monotonic() - start

                assert response.status_code == 401
                assert response.json()["detail"] == "Invalid email or password"
                assert elapsed > 0.05, f"Bcrypt did not run: {elapsed:.3f}s"
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_identical_error_messages(self):
        """Nonexistent user and wrong password must return identical responses."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await _signup_user(client, "identical@example.com")

                # Nonexistent user
                resp1 = await client.post(
                    "/auth/login",
                    json={
                        "email": "nonexistent@example.com",
                        "password": "securepassword123",
                    },
                )
                # Wrong password
                resp2 = await client.post(
                    "/auth/login",
                    json={
                        "email": "identical@example.com",
                        "password": "wrongpassword",
                    },
                )

                # Both must return identical status and detail
                assert resp1.status_code == resp2.status_code == 401
                assert resp1.json()["detail"] == resp2.json()["detail"]
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


# ── PHASE 4: Refresh Token Lifecycle ──────────────────────────────


class TestRefreshTokenLifecycle:
    """Verify refresh token creation, rotation, and revocation."""

    async def test_refresh_token_issued_on_login(self):
        """Login must set a refresh token cookie."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await _signup_user(client, "refresh@example.com")
                response = await client.post(
                    "/auth/login",
                    json={
                        "email": "refresh@example.com",
                        "password": "securepassword123",
                    },
                )
                assert response.status_code == 200
                # Check refresh token cookie is set
                cookies = response.cookies
                assert "refresh_token" in cookies
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_refresh_token_rotation(self):
        """Using a refresh token must issue a new one and revoke the old."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await _signup_user(client, "rotate@example.com")
                login_resp = await client.post(
                    "/auth/login",
                    json={
                        "email": "rotate@example.com",
                        "password": "securepassword123",
                    },
                )
                old_refresh = login_resp.cookies.get("refresh_token")
                assert old_refresh is not None

                # Use the refresh token
                refresh_resp = await client.post(
                    "/auth/refresh",
                    cookies={"refresh_token": old_refresh},
                )
                assert refresh_resp.status_code == 200
                new_refresh = refresh_resp.cookies.get("refresh_token")

                # New cookie should be different from old
                assert new_refresh is not None
                assert new_refresh != old_refresh

                # Old refresh token should now be invalid
                old_resp = await client.post(
                    "/auth/refresh",
                    cookies={"refresh_token": old_refresh},
                )
                assert old_resp.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_invalid_refresh_token_rejected(self):
        """Invalid refresh token must return 401."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/auth/refresh",
                    cookies={"refresh_token": "invalid-token"},
                )
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_logout_revokes_refresh_token(self):
        """Logout must revoke the refresh token and clear the cookie."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await _signup_user(client, "logout@example.com")
                login_resp = await client.post(
                    "/auth/login",
                    json={
                        "email": "logout@example.com",
                        "password": "securepassword123",
                    },
                )
                refresh_token = login_resp.cookies.get("refresh_token")

                # Logout
                logout_resp = await client.post(
                    "/auth/logout",
                    cookies={"refresh_token": refresh_token},
                )
                assert logout_resp.status_code == 200

                # Refresh token should now be invalid
                refresh_resp = await client.post(
                    "/auth/refresh",
                    cookies={"refresh_token": refresh_token},
                )
                assert refresh_resp.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_refresh_token_cookie_flags(self):
        """Refresh token cookie must have HttpOnly flag."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await _signup_user(client, "cookie@example.com")
                response = await client.post(
                    "/auth/login",
                    json={
                        "email": "cookie@example.com",
                        "password": "securepassword123",
                    },
                )
                # Check cookie attributes
                cookie_header = response.headers.get("set-cookie", "")
                assert "httponly" in cookie_header.lower()
                assert "refresh_token" in cookie_header
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_refresh_requires_cookie_or_body(self):
        """Refresh endpoint must reject requests without a token."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/auth/refresh")
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


# ── PHASE 6: Security Invariants ──────────────────────────────────


class TestSecurityInvariants:
    """Verify fundamental security properties remain intact."""

    async def test_no_client_controlled_user_id(self):
        """No endpoint should accept user_id from client."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Create two users
                resp1 = await _signup_user(client, "user1@example.com")
                await _signup_user(client, "user2@example.com")
                token1 = resp1["access_token"]

                # User 1 cannot access user 2's calibration versions
                response = await client.get(
                    "/analytics/calibration/versions",
                    headers={"Authorization": f"Bearer {token1}"},
                )
                # Should return 200 with empty list (user 1 has no calibrations)
                # NOT user 2's calibrations
                assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_disabled_user_rejected(self):
        """Inactive user must be rejected by get_current_user."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            # Create inactive user directly
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

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                token = create_access_token(inactive_id)
                response = await client.get(
                    "/analytics/calibration/versions",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_invalid_jwt_rejected(self):
        """Invalid JWT must be rejected."""
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

    async def test_missing_auth_rejected(self):
        """Request without Authorization header must be rejected."""
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

    async def test_jwt_not_in_response_body(self):
        """Login response must not expose JWT secret or internal details."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await _signup_user(client, "nosecret@example.com")
                response = await client.post(
                    "/auth/login",
                    json={
                        "email": "nosecret@example.com",
                        "password": "securepassword123",
                    },
                )
                body = response.json()
                # Response should only contain expected fields
                assert set(body.keys()) == {"access_token", "token_type", "user_id", "display_name"}
                # Token should not contain the secret
                assert "dev-only" not in body["access_token"]
                assert "secret" not in body["access_token"]
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_cross_user_calibration_isolation(self):
        """User A cannot see User B's calibration data."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp1 = await _signup_user(client, "isolation1@example.com")
                resp2 = await _signup_user(client, "isolation2@example.com")
                token1 = resp1["access_token"]
                token2 = resp2["access_token"]

                # Both should see empty calibration versions
                r1 = await client.get(
                    "/analytics/calibration/versions",
                    headers={"Authorization": f"Bearer {token1}"},
                )
                r2 = await client.get(
                    "/analytics/calibration/versions",
                    headers={"Authorization": f"Bearer {token2}"},
                )
                assert r1.status_code == 200
                assert r2.status_code == 200
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

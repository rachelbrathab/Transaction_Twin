"""Shared pytest fixtures for backend tests."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _test_env(monkeypatch):
    """Set test environment variables before every test."""
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")


@pytest.fixture
async def client():
    """Async test client for the FastAPI application.

    Uses httpx AsyncClient with ASGI transport so no real HTTP server is needed.
    """
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

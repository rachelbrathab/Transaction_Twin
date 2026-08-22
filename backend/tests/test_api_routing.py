"""Tests for API routing structure and versioning."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_v1_health_route_exists(client: AsyncClient):
    """GET /api/v1/health endpoint is registered (returns error without DB, not 404)."""
    response = await client.get("/api/v1/health")
    # Without a real DB the route exists but will fail — should NOT be 404
    assert response.status_code != 404
    # The response body should follow the error format if it's an error
    if response.status_code >= 400:
        body = response.json()
        assert "error" in body


@pytest.mark.asyncio
async def test_unknown_route_returns_404(client: AsyncClient):
    """Unknown routes return 404."""
    response = await client.get("/api/v1/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_docs_endpoint(client: AsyncClient):
    """Swagger docs are accessible."""
    response = await client.get("/docs")
    assert response.status_code == 200

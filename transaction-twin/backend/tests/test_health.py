"""Tests for health check endpoints and application startup."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_health(client: AsyncClient):
    """GET /health returns ok without database dependency."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_root_health_content_type(client: AsyncClient):
    """Health endpoint returns JSON content type."""
    response = await client.get("/health")
    assert "application/json" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_openapi_spec_available(client: AsyncClient):
    """OpenAPI docs are accessible."""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert "openapi" in spec
    assert "/health" in spec["paths"]

"""Tests for POST /api/v1/intents/parse endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestIntentAPI:
    @pytest.mark.asyncio
    async def test_parse_endpoint_exists(self, client):
        response = await client.post(
            "/intents/parse",
            json={
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "agent_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "original_request": "Buy shoes under ₹4,000",
                "default_currency": "INR",
            },
        )
        # Will fail ownership validation but endpoint exists
        assert response.status_code in (200, 400, 422, 500)

    @pytest.mark.asyncio
    async def test_parse_missing_fields(self, client):
        response = await client.post(
            "/intents/parse",
            json={"original_request": "Buy shoes"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_parse_empty_body(self, client):
        response = await client.post("/intents/parse", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_parse_rejects_invalid_uuids(self, client):
        response = await client.post(
            "/intents/parse",
            json={
                "user_id": "invalid",
                "agent_id": "invalid",
                "original_request": "Buy shoes",
            },
        )
        # Engine catches invalid UUIDs gracefully, returns rejected status
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"

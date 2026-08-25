"""Tests for Policy Engine API endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


class TestPolicyEvaluationAPI:
    """Tests for POST /policies/evaluate endpoint."""

    def setup_method(self) -> None:
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_endpoint_exists(self) -> None:
        """Endpoint exists and returns a response."""
        response = self.client.post(
            "/policies/evaluate",
            json={"intent_id": "00000000-0000-0000-0000-000000000000",
                  "proposal": {}},
        )
        # Should not be 404 (endpoint exists)
        assert response.status_code != 404

    def test_invalid_intent_id_format(self) -> None:
        """Invalid UUID format returns 422."""
        response = self.client.post(
            "/policies/evaluate",
            json={"intent_id": "not-a-uuid", "proposal": {}},
        )
        assert response.status_code == 422

    def test_missing_fields_returns_error(self) -> None:
        """Missing required fields returns error."""
        response = self.client.post(
            "/policies/evaluate",
            json={},
        )
        assert response.status_code in (422, 500)

    def test_invalid_proposal_returns_error(self) -> None:
        """Malformed proposal returns error."""
        response = self.client.post(
            "/policies/evaluate",
            json={
                "intent_id": "00000000-0000-0000-0000-000000000000",
                "proposal": {
                    "amount": -500,
                    "user_id": "not-a-uuid",
                    "agent_id": "not-a-uuid",
                    "intent_id": "not-a-uuid",
                    "transaction_type": "purchase",
                    "idempotency_key": "key1",
                },
            },
        )
        # Should fail validation (negative amount or invalid UUIDs)
        assert response.status_code in (422, 403, 500)

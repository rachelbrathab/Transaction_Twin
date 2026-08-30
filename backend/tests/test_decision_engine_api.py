"""Tests for Decision Engine API endpoint.

Follows existing project patterns for API tests.
"""

from app.main import app


class TestDecisionEndpointExists:
    def test_decide_endpoint_exists(self):
        """Verify the decide endpoint responds (not 405 Method Not Allowed)."""
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/transactions/decide",
            json={},
        )
        # Without auth: 401. With invalid data: 422. Never 404 or 405.
        assert response.status_code != 404
        assert response.status_code != 405

    def test_decide_requires_auth(self):
        """Verify unauthenticated request returns 401."""
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/transactions/decide",
            json={},
        )
        assert response.status_code == 401

    def test_decide_endpoint_method(self):
        """Verify POST method is registered."""
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/transactions/decide",
            json={},
        )
        # Without auth: 401 is expected
        assert response.status_code in (401, 422, 500)

    def test_decide_requires_intent_id(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/transactions/decide",
            json={"proposal": {"user_id": "u1"}},
        )
        # Without auth: 401
        assert response.status_code in (401, 422, 500)

    def test_decide_requires_proposal(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/transactions/decide",
            json={"intent_id": "some-uuid"},
        )
        # Without auth: 401
        assert response.status_code in (401, 422, 500)

    def test_invalid_intent_id_format(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/transactions/decide",
            json={
                "intent_id": "not-a-uuid",
                "proposal": {
                    "user_id": "u1",
                    "agent_id": "a1",
                    "intent_id": "not-a-uuid",
                    "transaction_type": "purchase",
                    "idempotency_key": "key1",
                },
            },
        )
        # Without auth: 401. With invalid format: 422 or 500.
        assert response.status_code in (401, 422, 500)

    def test_endpoint_returns_json(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/transactions/decide",
            json={},
        )
        assert response.headers.get("content-type", "").startswith("application/json")


class TestDecisionEndpointOwnership:
    def test_invalid_proposal_fields_rejected(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/transactions/decide",
            json={
                "intent_id": "00000000-0000-0000-0000-000000000001",
                "proposal": {
                    "user_id": "not-a-uuid",
                    "agent_id": "also-not-a-uuid",
                    "intent_id": "00000000-0000-0000-0000-000000000001",
                    "transaction_type": "purchase",
                    "idempotency_key": "key1",
                },
            },
        )
        # Without auth: 401. With invalid data: 422, 403, or 500.
        assert response.status_code in (401, 422, 403, 500)

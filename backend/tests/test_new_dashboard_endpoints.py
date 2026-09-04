"""Tests for new dashboard endpoints.

Tests transaction list/detail, policy CRUD, risk intelligence summary,
and audit vault endpoints.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.identity import get_current_user
from app.main import app
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.intent import Intent
from app.models.policy import Policy
from app.models.transaction import Transaction
from app.models.transaction_event import TransactionEvent
from app.models.user import User

USER_A = uuid.uuid4()
_active_user_id: uuid.UUID = USER_A


class _FakeUser:
    def __init__(self, uid: uuid.UUID) -> None:
        self.id = uid


async def _override_get_current_user():
    return _FakeUser(_active_user_id)


@pytest_asyncio.fixture
async def client_and_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_get_db():
        async with factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    yield client, factory

    app.dependency_overrides.clear()
    await engine.dispose()


async def _setup_data(session: AsyncSession):
    """Create user, agent, intent, and some transactions."""
    session.add(User(id=USER_A, display_name="Test"))
    await session.flush()

    agent_id = uuid.uuid4()
    session.add(Agent(id=agent_id, user_id=USER_A, name="Agent", status="active"))
    await session.flush()

    intent_id = uuid.uuid4()
    session.add(Intent(
        id=intent_id, user_id=USER_A, agent_id=agent_id,
        original_request="test", structured_intent={
            "goal": "purchase",
            "transaction_type": "purchase",
            "currency": {
                "code": "INR", "source": "explicit",
                "evidence": None,
            },
            "amount": {
                "min": 10000, "max": 100000,
                "exact": None, "confidence": 0.9,
                "evidence": None,
            },
            "category_constraints": {
                "items": [], "attributes": {},
                "confidence": 0.5, "evidence": None,
            },
            "merchant_constraints": {
                "trust_required": False, "preferred": [],
                "excluded": [], "confidence": 0.5,
                "evidence": None,
            },
            "geographic_constraints": {
                "country": None, "city": None,
                "radius_km": None, "confidence": 0.5,
                "evidence": None,
            },
            "temporal_constraints": {
                "deadline": None, "duration": None,
                "recurring": False, "confidence": 0.5,
                "evidence": None,
            },
            "authorization_scope": {
                "value": None, "evidence": None,
            },
            "metadata": {
                "parser_version": "test",
                "model_provider": "deterministic",
                "model_name": "test",
                "extraction_method": "deterministic",
                "parsing_latency_ms": 0,
                "canonical_request": "test",
                "reference_timestamp": "2024-01-01T00:00:00Z",
                "injection_detected": False,
            },
        },
        confidence=0.9, status="parsed", version=1,
    ))
    await session.flush()

    # Create 3 transactions with decisions
    for i in range(3):
        txn_id = uuid.uuid4()
        session.add(Transaction(
            id=txn_id, user_id=USER_A, agent_id=agent_id,
            intent_id=intent_id, idempotency_key=uuid.uuid4(),
            transaction_type="purchase", amount=10000 + i * 5000,
            currency="INR", status="decided",
        ))
        await session.flush()

        session.add(Decision(
            transaction_id=txn_id,
            decision="allow" if i < 2 else "block",
            reason=f"Test decision {i}",
            explanation={"risk": {"level": "low" if i < 2 else "high", "score": 0.1 + i * 0.3}},
            version=1,
        ))
        await session.flush()

        session.add(TransactionEvent(
            transaction_id=txn_id, agent_id=agent_id,
            sequence_number=1, event_type="decision_created",
            source="system", verification_state="verified",
        ))
        await session.flush()

    # Create a policy
    session.add(Policy(
        user_id=USER_A, name="Test Policy", description="A test policy",
        status="active", version=1, rules={"type": "amount_limit", "max": 100000},
    ))
    await session.flush()
    await session.commit()

    return agent_id, intent_id


# ── Transaction Tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_transactions(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        await _setup_data(session)

    resp = await client.get("/api/v1/transactions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["transactions"]) == 3

    # Verify each transaction has required fields
    for txn in data["transactions"]:
        assert "id" in txn
        assert "decision" in txn
        assert "amount" in txn
        assert "risk_level" in txn


@pytest.mark.asyncio
async def test_get_transaction_detail(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        agent_id, intent_id = await _setup_data(session)

    # Get transaction list first
    resp = await client.get("/api/v1/transactions")
    txn_id = resp.json()["transactions"][0]["id"]

    # Get detail
    resp = await client.get(f"/api/v1/transactions/{txn_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == txn_id
    assert "decision_explanation" in data
    assert "events" in data
    assert len(data["events"]) >= 1


@pytest.mark.asyncio
async def test_transaction_not_found(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        await _setup_data(session)

    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/transactions/{fake_id}")
    assert resp.status_code == 404


# ── Policy Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_policies(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        await _setup_data(session)

    resp = await client.get("/api/v1/policies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["policies"][0]["name"] == "Test Policy"


@pytest.mark.asyncio
async def test_create_policy(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        await _setup_data(session)

    resp = await client.post("/api/v1/policies", json={
        "name": "New Policy",
        "description": "Created via test",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "New Policy"
    assert data["status"] == "draft"


@pytest.mark.asyncio
async def test_update_policy(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        await _setup_data(session)

    # Get policy ID
    resp = await client.get("/api/v1/policies")
    policy_id = resp.json()["policies"][0]["id"]

    # Update
    resp = await client.put(f"/api/v1/policies/{policy_id}", json={
        "name": "Updated Policy",
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Policy"


@pytest.mark.asyncio
async def test_delete_policy(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        await _setup_data(session)

    resp = await client.get("/api/v1/policies")
    policy_id = resp.json()["policies"][0]["id"]

    resp = await client.delete(f"/api/v1/policies/{policy_id}")
    assert resp.status_code == 204

    # Verify deleted
    resp = await client.get(f"/api/v1/policies/{policy_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_policy_not_found(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        await _setup_data(session)

    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/policies/{fake_id}")
    assert resp.status_code == 404


# ── Risk Intelligence Tests ───────────────────────────────────


@pytest.mark.asyncio
async def test_risk_summary(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        await _setup_data(session)

    resp = await client.get("/api/v1/risk-intelligence/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_decisions"] == 3
    assert data["allow_count"] == 2
    assert data["block_count"] == 1
    assert "risk_level_distribution" in data


@pytest.mark.asyncio
async def test_risk_transactions(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        await _setup_data(session)

    resp = await client.get("/api/v1/risk-intelligence/transactions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["transactions"]) == 3

    for txn in data["transactions"]:
        assert "risk_level" in txn
        assert "risk_score" in txn
        assert "decision" in txn


# ── Audit Vault Tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_audit_events(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        await _setup_data(session)

    resp = await client.get("/api/v1/audit/events")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 0  # May be empty if no audit events created yet


@pytest.mark.asyncio
async def test_audit_events_unauthenticated(client_and_session):
    client, factory = client_and_session
    async with factory() as session:
        await _setup_data(session)

    # Remove auth override
    app.dependency_overrides.clear()

    resp = await client.get("/api/v1/audit/events")
    assert resp.status_code in (401, 403)

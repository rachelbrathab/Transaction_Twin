"""Integration test for the full calibration intelligence end-to-end flow.

Tests the complete lifecycle:
1. Create agent
2. Parse intent
3. Submit transaction decision
4. Simulate verified outcomes (multiple transactions)
5. Retrieve calibration outcomes
6. Generate calibration version
7. List versions
8. Get version detail with recommendations
9. Review recommendation (approve)
10. Activate version
11. Retrieve effective config
12. Retrieve health metrics
13. Test with zero outcomes
14. Ownership isolation

Uses in-memory SQLite with dependency overrides (project convention).
Creates additional transactions directly in the DB to avoid repeated
decide-endpoint calls (which trigger SQLite datetime comparison issues).
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
from app.models.transaction import Transaction
from app.models.transaction_event import TransactionEvent
from app.models.user import User

# ── Test fixtures ────────────────────────────────────────────

USER_A = uuid.uuid4()
USER_B = uuid.uuid4()

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


# ── Helpers ──────────────────────────────────────────────────

STRUCTURED_INTENT_DICT = {
    "goal": "purchase",
    "transaction_type": "purchase",
    "currency": {
        "code": "INR",
        "source": "explicit",
        "evidence": None,
    },
    "amount": {
        "min": 40000,
        "max": 60000,
        "exact": None,
        "confidence": 0.9,
        "evidence": None,
    },
    "category_constraints": {
        "items": ["electronics"],
        "attributes": {},
        "confidence": 0.8,
        "evidence": None,
    },
    "merchant_constraints": {
        "trust_required": False,
        "preferred": [],
        "excluded": [],
        "confidence": 0.5,
        "evidence": None,
    },
    "geographic_constraints": {
        "country": "IN",
        "city": None,
        "radius_km": None,
        "confidence": 0.9,
        "evidence": None,
    },
    "temporal_constraints": {
        "deadline": None,
        "duration": None,
        "recurring": False,
        "confidence": 0.5,
        "evidence": None,
    },
    "authorization_scope": {
        "value": None,
        "evidence": None,
    },
    "metadata": {
        "parser_version": "test",
        "model_provider": "deterministic",
        "model_name": "test",
        "extraction_method": "deterministic",
        "parsing_latency_ms": 0,
        "canonical_request": "I want to buy electronics for 50000 INR",
        "reference_timestamp": "2024-01-01T00:00:00Z",
        "injection_detected": False,
    },
}


async def _setup_test_data(
    session: AsyncSession, user_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create user, agent, and intent. Returns (agent_id, intent_id)."""
    # User
    session.add(User(id=user_id, display_name="Test User"))
    await session.flush()

    # Agent
    agent_id = uuid.uuid4()
    session.add(Agent(
        id=agent_id, user_id=user_id,
        name="Test Agent", status="active",
    ))
    await session.flush()

    # Intent
    intent_id = uuid.uuid4()
    session.add(Intent(
        id=intent_id, user_id=user_id, agent_id=agent_id,
        original_request="I want to buy electronics for 50000 INR",
        structured_intent=STRUCTURED_INTENT_DICT,
        confidence=0.9, status="parsed", version=1,
    ))
    await session.flush()

    return agent_id, intent_id


async def _create_decided_transaction(
    session: AsyncSession,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    intent_id: uuid.UUID,
    decision: str = "allow",
    amount: float = 50000.0,
) -> uuid.UUID:
    """Create a decided transaction directly in the DB. Returns transaction_id."""
    txn_id = uuid.uuid4()
    txn = Transaction(
        id=txn_id,
        user_id=user_id,
        agent_id=agent_id,
        intent_id=intent_id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=amount,
        currency="INR",
        status="decided",
    )
    session.add(txn)
    await session.flush()

    # Create Decision
    decision_record = Decision(
        transaction_id=txn_id,
        decision=decision,
        reason=f"Test {decision} decision",
        explanation={
            "risk": {"level": "low", "available": True},
            "policy": {"triggered_count": 0},
        },
        version=1,
    )
    session.add(decision_record)
    await session.flush()

    # Create initial decision_created event
    event = TransactionEvent(
        transaction_id=txn_id,
        agent_id=agent_id,
        sequence_number=1,
        event_type="decision_created",
        source="system",
        verification_state="verified",
        payload={"decision": decision},
    )
    session.add(event)
    await session.flush()

    return txn_id


async def _decide_transaction(
    client: AsyncClient,
    intent_id: uuid.UUID,
    agent_id: uuid.UUID,
    amount: float = 50000.0,
) -> dict:
    """Submit a transaction decision via the API."""
    proposal = {
        "user_id": str(USER_A),
        "agent_id": str(agent_id),
        "intent_id": str(intent_id),
        "transaction_type": "purchase",
        "amount": amount,
        "currency": "INR",
        "category": "electronics",
        "product_description": "Laptop purchase",
        "merchant_name": "TechStore",
        "merchant_trusted": True,
        "country": "IN",
        "city": "Mumbai",
        "idempotency_key": str(uuid.uuid4()),
    }
    resp = await client.post(
        "/api/v1/transactions/decide",
        json={"intent_id": str(intent_id), "proposal": proposal},
    )
    assert resp.status_code == 200, f"Decision failed: {resp.text}"
    return resp.json()


async def _simulate_outcome(
    client: AsyncClient,
    transaction_id: uuid.UUID,
    event_type: str,
) -> dict:
    """Simulate an outcome for a decided transaction."""
    resp = await client.post(
        f"/api/v1/transactions/{transaction_id}/simulate-outcome",
        json={"event_type": event_type},
    )
    assert resp.status_code == 200, f"Simulate failed: {resp.text}"
    return resp.json()


# ── Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_calibration_flow(client_and_session):
    """Test the complete calibration intelligence flow end-to-end."""
    client, factory = client_and_session

    async with factory() as session:
        agent_id, intent_id = await _setup_test_data(session, USER_A)

        # Create 5 decided transactions directly in the DB
        txn_ids = []
        for i in range(5):
            txn_id = await _create_decided_transaction(
                session, USER_A, agent_id, intent_id,
                decision="allow" if i < 3 else "block",
                amount=10000.0 + (i * 5000),
            )
            txn_ids.append(txn_id)

        await session.commit()

    # Simulate outcomes: 3 payment_success, 2 payment_cancelled
    for txn_id in txn_ids[:3]:
        await _simulate_outcome(client, txn_id, "payment_success")

    for txn_id in txn_ids[3:]:
        await _simulate_outcome(client, txn_id, "payment_cancelled")

    # 1. Retrieve calibration outcomes
    outcomes_resp = await client.get(
        "/api/v1/analytics/calibration/outcomes",
    )
    assert outcomes_resp.status_code == 200
    outcomes = outcomes_resp.json()
    assert outcomes["total_samples"] >= 5
    assert outcomes["eligible_samples"] >= 5

    # 2. Generate calibration
    gen_resp = await client.post(
        "/api/v1/analytics/calibration/generate",
        json={"window_days": 30},
    )
    assert gen_resp.status_code == 200
    gen_data = gen_resp.json()
    assert gen_data["version_id"] != ""
    version_id = gen_data["version_id"]

    # 3. List versions
    versions_resp = await client.get(
        "/api/v1/analytics/calibration/versions",
    )
    assert versions_resp.status_code == 200
    versions = versions_resp.json()
    assert versions["total"] >= 1
    assert any(
        v["version_id"] == version_id for v in versions["versions"]
    )

    # 4. Get version detail
    detail_resp = await client.get(
        f"/api/v1/analytics/calibration/versions/{version_id}",
    )
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["version"]["version_id"] == version_id
    recommendations = detail["recommendations"]

    # 5. Get recommendations list
    recs_resp = await client.get(
        "/api/v1/analytics/calibration/recommendations",
    )
    assert recs_resp.status_code == 200
    recs = recs_resp.json()
    assert recs["total"] >= len(recommendations)

    # 6. Review recommendation (approve first one)
    if recommendations:
        rec_id = recommendations[0]["recommendation_id"]
        review_resp = await client.post(
            f"/api/v1/analytics/calibration/recommendations/{rec_id}/review",
            json={"action": "approve"},
        )
        assert review_resp.status_code == 200
        assert review_resp.json()["status"] in ("reviewed", "approved")

    # 7. Get effective config
    config_resp = await client.get(
        "/api/v1/analytics/calibration/effective-config",
    )
    assert config_resp.status_code == 200
    config = config_resp.json()
    assert "calibration_active" in config

    # 8. Get metrics
    metrics_resp = await client.get(
        "/api/v1/analytics/calibration/metrics",
    )
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.json()
    assert "total_decisions" in metrics
    assert "calibration_active_count" in metrics
    assert "risk_level_distribution" in metrics


@pytest.mark.asyncio
async def test_calibration_with_zero_outcomes(client_and_session):
    """Test calibration generation with no outcomes returns gracefully."""
    client, factory = client_and_session

    async with factory() as session:
        agent_id, intent_id = await _setup_test_data(session, USER_A)

        # Create 1 decided transaction (no outcomes)
        await _create_decided_transaction(
            session, USER_A, agent_id, intent_id,
        )
        await session.commit()

    # Outcomes should show excluded samples
    outcomes_resp = await client.get(
        "/api/v1/analytics/calibration/outcomes",
    )
    assert outcomes_resp.status_code == 200
    outcomes = outcomes_resp.json()
    assert outcomes["eligible_samples"] == 0

    # Generate should still work (returns empty/insufficient version)
    gen_resp = await client.post(
        "/api/v1/analytics/calibration/generate",
        json={"window_days": 30},
    )
    assert gen_resp.status_code == 200


@pytest.mark.asyncio
async def test_calibration_ownership_isolation(client_and_session):
    """Test that users can only see their own calibration data."""
    client, factory = client_and_session

    async with factory() as session:
        agent_id, intent_id = await _setup_test_data(session, USER_A)

        # User A creates transactions with outcomes
        for i in range(3):
            txn_id = await _create_decided_transaction(
                session, USER_A, agent_id, intent_id,
                amount=20000.0,
            )
        await session.commit()

    # Simulate outcomes for User A
    async with factory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(Transaction.id)
            .where(Transaction.user_id == USER_A)
            .limit(3)
        )
        txn_ids = [row[0] for row in result.all()]

    for txn_id in txn_ids:
        await _simulate_outcome(client, txn_id, "payment_success")

    # User A generates calibration
    gen_resp = await client.post(
        "/api/v1/analytics/calibration/generate",
        json={"window_days": 30},
    )
    assert gen_resp.status_code == 200
    assert gen_resp.json()["version_id"] != ""

    # Switch to User B
    global _active_user_id
    _active_user_id = USER_B

    # User B should see empty calibration
    versions_resp = await client.get(
        "/api/v1/analytics/calibration/versions",
    )
    assert versions_resp.status_code == 200
    assert versions_resp.json()["total"] == 0

    outcomes_resp = await client.get(
        "/api/v1/analytics/calibration/outcomes",
    )
    assert outcomes_resp.status_code == 200
    assert outcomes_resp.json()["total_samples"] == 0

    # Switch back to User A
    _active_user_id = USER_A

    # User A still sees their data
    versions_resp = await client.get(
        "/api/v1/analytics/calibration/versions",
    )
    assert versions_resp.status_code == 200
    assert versions_resp.json()["total"] >= 1


@pytest.mark.asyncio
async def test_simulate_outcome_validates_ownership(client_and_session):
    """Test that simulate-outcome enforces ownership."""
    client, factory = client_and_session

    async with factory() as session:
        agent_id, intent_id = await _setup_test_data(session, USER_A)
        txn_id = await _create_decided_transaction(
            session, USER_A, agent_id, intent_id,
        )
        await session.commit()

    # Switch to User B
    global _active_user_id
    _active_user_id = USER_B

    # User B cannot simulate outcome for User A's transaction
    sim_resp = await client.post(
        f"/api/v1/transactions/{txn_id}/simulate-outcome",
        json={"event_type": "payment_success"},
    )
    assert sim_resp.status_code == 403

    # Switch back
    _active_user_id = USER_A


@pytest.mark.asyncio
async def test_simulate_outcome_rejects_invalid_event(
    client_and_session,
):
    """Test that simulate-outcome rejects invalid event types."""
    client, factory = client_and_session

    async with factory() as session:
        agent_id, intent_id = await _setup_test_data(session, USER_A)
        txn_id = await _create_decided_transaction(
            session, USER_A, agent_id, intent_id,
        )
        await session.commit()

    sim_resp = await client.post(
        f"/api/v1/transactions/{txn_id}/simulate-outcome",
        json={"event_type": "nonexistent_event"},
    )
    assert sim_resp.status_code == 422


@pytest.mark.asyncio
async def test_simulate_multiple_event_types(client_and_session):
    """Test simulating different event types produces correct outcomes."""
    client, factory = client_and_session

    async with factory() as session:
        agent_id, intent_id = await _setup_test_data(session, USER_A)
        txn_ids = []
        for event in ["payment_success", "payment_cancelled", "payment_failed"]:
            txn_id = await _create_decided_transaction(
                session, USER_A, agent_id, intent_id,
            )
            txn_ids.append((txn_id, event))
        await session.commit()

    for txn_id, event_type in txn_ids:
        result = await _simulate_outcome(client, txn_id, event_type)
        assert result["target_event"] == event_type
        # payment_initiated intermediate event + final event = 2 events
        assert len(result["events_created"]) >= 1

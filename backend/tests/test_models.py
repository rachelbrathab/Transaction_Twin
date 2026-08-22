"""Tests for all 11 SQLAlchemy models — creation, relationships, and constraints."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Agent,
    AgentCapability,
    AuditEvent,
    Decision,
    Intent,
    Merchant,
    Policy,
    RiskAssessment,
    Transaction,
    TransactionEvent,
    User,
)

# ── Helpers ────────────────────────────────────────────────────────


async def _create_user(db: AsyncSession, **overrides) -> User:
    defaults = {"display_name": "Test User", "status": "active"}
    defaults.update(overrides)
    user = User(**defaults)
    db.add(user)
    await db.flush()
    return user


async def _create_agent(db: AsyncSession, user: User, **overrides) -> Agent:
    defaults = {"user_id": user.id, "name": "Test Agent", "status": "active"}
    defaults.update(overrides)
    agent = Agent(**defaults)
    db.add(agent)
    await db.flush()
    return agent


async def _create_intent(db: AsyncSession, user: User, agent: Agent, **overrides) -> Intent:
    defaults = {
        "user_id": user.id,
        "agent_id": agent.id,
        "original_request": "Buy shoes under 4000",
    }
    defaults.update(overrides)
    intent = Intent(**defaults)
    db.add(intent)
    await db.flush()
    return intent


async def _create_policy(db: AsyncSession, user: User, **overrides) -> Policy:
    defaults = {"user_id": user.id, "name": "Default Policy", "version": 1}
    defaults.update(overrides)
    policy = Policy(**defaults)
    db.add(policy)
    await db.flush()
    return policy


async def _create_merchant(db: AsyncSession, **overrides) -> Merchant:
    defaults = {"name": "Test Merchant", "status": "active"}
    defaults.update(overrides)
    merchant = Merchant(**defaults)
    db.add(merchant)
    await db.flush()
    return merchant


# ── Model Creation Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_creation(db_session: AsyncSession):
    user = await _create_user(db_session, display_name="Alice", external_reference="ext-001")
    assert user.id is not None
    assert user.display_name == "Alice"
    assert user.external_reference == "ext-001"
    assert user.status == "active"
    assert user.created_at is not None
    assert user.updated_at is not None


@pytest.mark.asyncio
async def test_agent_creation(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user, name="Shopping Bot")
    assert agent.id is not None
    assert agent.user_id == user.id
    assert agent.name == "Shopping Bot"
    assert agent.status == "active"
    assert agent.trust_score is None


@pytest.mark.asyncio
async def test_agent_trust_score_range(db_session: AsyncSession):
    user = await _create_user(db_session)
    # Valid trust score
    agent = await _create_agent(db_session, user, trust_score=0.75)
    assert agent.trust_score is not None

    # Boundary values
    agent2 = Agent(user_id=user.id, name="Bot2", trust_score=0)
    db_session.add(agent2)
    await db_session.flush()

    agent3 = Agent(user_id=user.id, name="Bot3", trust_score=1)
    db_session.add(agent3)
    await db_session.flush()

    # Invalid trust score (should fail)
    agent4 = Agent(user_id=user.id, name="Bot4", trust_score=1.5)
    db_session.add(agent4)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_agent_capability_creation(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    cap = AgentCapability(agent_id=agent.id, capability="purchase")
    db_session.add(cap)
    await db_session.flush()
    assert cap.id is not None
    assert cap.capability == "purchase"


@pytest.mark.asyncio
async def test_agent_capability_duplicate_fails(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    cap1 = AgentCapability(agent_id=agent.id, capability="purchase")
    cap2 = AgentCapability(agent_id=agent.id, capability="purchase")
    db_session.add(cap1)
    await db_session.flush()
    db_session.add(cap2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_intent_creation(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    assert intent.id is not None
    assert intent.user_id == user.id
    assert intent.agent_id == agent.id
    assert intent.original_request == "Buy shoes under 4000"
    assert intent.status == "active"
    assert intent.currency == "INR"


@pytest.mark.asyncio
async def test_intent_amount_bounds(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    # Valid bounds: min < max
    intent = await _create_intent(db_session, user, agent, min_amount=100, max_amount=500)
    assert intent.min_amount is not None

    # Invalid bounds: min > max (should fail)
    intent2 = Intent(
        user_id=user.id,
        agent_id=agent.id,
        original_request="test",
        min_amount=500,
        max_amount=100,
    )
    db_session.add(intent2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_intent_no_policy_id(db_session: AsyncSession):
    """Intent should NOT have a policy_id column."""
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    # Verify no policy_id attribute
    assert not hasattr(intent, "policy_id")


@pytest.mark.asyncio
async def test_policy_creation(db_session: AsyncSession):
    user = await _create_user(db_session)
    policy = await _create_policy(db_session, user)
    assert policy.id is not None
    assert policy.name == "Default Policy"
    assert policy.version == 1
    assert policy.status == "draft"


@pytest.mark.asyncio
async def test_policy_version_unique(db_session: AsyncSession):
    user = await _create_user(db_session)
    p1 = await _create_policy(db_session, user, name="Spending Limit", version=1)
    p2 = await _create_policy(db_session, user, name="Spending Limit", version=2)
    assert p1.id != p2.id

    # Duplicate (same user + name + version) should fail
    p3 = Policy(user_id=user.id, name="Spending Limit", version=1)
    db_session.add(p3)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_merchant_creation(db_session: AsyncSession):
    merchant = await _create_merchant(db_session, name="Amazon India", category="ecommerce")
    assert merchant.id is not None
    assert merchant.name == "Amazon India"
    assert merchant.status == "active"
    assert merchant.trust_score is None


@pytest.mark.asyncio
async def test_merchant_trust_score_range(db_session: AsyncSession):
    m = await _create_merchant(db_session, trust_score=0.5)
    assert m.trust_score == 0.5

    m_bad = Merchant(name="Bad", trust_score=2.0)
    db_session.add(m_bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_transaction_creation(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    policy = await _create_policy(db_session, user)
    merchant = await _create_merchant(db_session)

    tx = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        policy_id=policy.id,
        merchant_id=merchant.id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=2999.99,
        currency="INR",
    )
    db_session.add(tx)
    await db_session.flush()
    assert tx.id is not None
    assert tx.amount == 2999.99
    assert tx.status == "proposed"


@pytest.mark.asyncio
async def test_transaction_idempotency_per_agent(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)

    idem_key = uuid.uuid4()
    tx1 = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        idempotency_key=idem_key,
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx1)
    await db_session.flush()

    # Same agent + same idempotency_key should fail
    tx2 = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        idempotency_key=idem_key,
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

    # Different agent + same idempotency_key should succeed
    agent2 = await _create_agent(db_session, user, name="Bot2")
    tx3 = Transaction(
        user_id=user.id,
        agent_id=agent2.id,
        intent_id=intent.id,
        idempotency_key=idem_key,
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx3)
    await db_session.flush()
    assert tx3.id is not None


@pytest.mark.asyncio
async def test_transaction_amount_positive(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)

    tx = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=-100,
    )
    db_session.add(tx)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_transaction_event_creation(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    tx = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx)
    await db_session.flush()

    event = TransactionEvent(
        transaction_id=tx.id,
        agent_id=agent.id,
        sequence_number=1,
        event_type="intent_created",
        payload={"source": "test"},
    )
    db_session.add(event)
    await db_session.flush()
    assert event.id is not None
    assert event.sequence_number == 1


@pytest.mark.asyncio
async def test_transaction_event_sequence_unique(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    tx = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx)
    await db_session.flush()

    e1 = TransactionEvent(
        transaction_id=tx.id, agent_id=agent.id,
        sequence_number=1, event_type="start",
    )
    e2 = TransactionEvent(
        transaction_id=tx.id, agent_id=agent.id,
        sequence_number=1, event_type="dup",
    )
    db_session.add(e1)
    await db_session.flush()
    db_session.add(e2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_transaction_event_sequence_positive(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    tx = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx)
    await db_session.flush()

    e = TransactionEvent(
        transaction_id=tx.id, agent_id=agent.id,
        sequence_number=0, event_type="bad",
    )
    db_session.add(e)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_risk_assessment_creation(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    tx = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx)
    await db_session.flush()

    ra = RiskAssessment(
        transaction_id=tx.id,
        overall_score=0.3,
        intent_match_score=0.9,
        behavioral_risk=0.1,
        agent_trust_score=0.8,
        policy_risk=0.2,
        velocity_risk=0.0,
        merchant_risk=0.5,
        model_version="v1.0",
    )
    db_session.add(ra)
    await db_session.flush()
    assert ra.id is not None
    assert ra.overall_score == 0.3
    assert ra.model_version == "v1.0"


@pytest.mark.asyncio
async def test_risk_assessment_score_bounds(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    tx = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx)
    await db_session.flush()

    # Invalid score > 1
    ra = RiskAssessment(transaction_id=tx.id, overall_score=1.5)
    db_session.add(ra)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

    # Invalid score < 0
    ra2 = RiskAssessment(transaction_id=tx.id, overall_score=-0.1)
    db_session.add(ra2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_decision_creation(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    tx = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx)
    await db_session.flush()

    dec = Decision(
        transaction_id=tx.id,
        decision="ALLOW",
        reason="Low risk",
        version=1,
    )
    db_session.add(dec)
    await db_session.flush()
    assert dec.id is not None
    assert dec.decision == "ALLOW"
    assert dec.version == 1


@pytest.mark.asyncio
async def test_decision_version_unique(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    tx = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx)
    await db_session.flush()

    d1 = Decision(transaction_id=tx.id, decision="ALLOW", version=1)
    d2 = Decision(transaction_id=tx.id, decision="BLOCK", version=2)
    db_session.add(d1)
    await db_session.flush()
    db_session.add(d2)
    await db_session.flush()

    # Duplicate version should fail
    d3 = Decision(transaction_id=tx.id, decision="REVIEW", version=1)
    db_session.add(d3)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_audit_event_creation(db_session: AsyncSession):
    user = await _create_user(db_session)
    event = AuditEvent(
        entity_type="user",
        entity_id=user.id,
        event_type="user_created",
        actor_type="system",
    )
    db_session.add(event)
    await db_session.flush()
    assert event.id is not None
    assert event.previous_hash is None
    assert event.current_hash is None


# ── Relationship Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_agent_relationship(db_session: AsyncSession):
    user = await _create_user(db_session)
    await _create_agent(db_session, user, name="Bot1")
    await _create_agent(db_session, user, name="Bot2")

    result = await db_session.execute(
        select(Agent).where(Agent.user_id == user.id)
    )
    agents = result.scalars().all()
    assert len(agents) == 2


@pytest.mark.asyncio
async def test_agent_capability_relationship(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    c1 = AgentCapability(agent_id=agent.id, capability="search")
    c2 = AgentCapability(agent_id=agent.id, capability="purchase")
    db_session.add_all([c1, c2])
    await db_session.flush()

    result = await db_session.execute(
        select(AgentCapability).where(AgentCapability.agent_id == agent.id)
    )
    caps = result.scalars().all()
    assert len(caps) == 2


@pytest.mark.asyncio
async def test_cascade_delete_user_removes_agents(db_session: AsyncSession):
    user = await _create_user(db_session)
    await _create_agent(db_session, user)
    user_id = user.id

    await db_session.delete(user)
    await db_session.flush()

    result = await db_session.execute(select(Agent).where(Agent.user_id == user_id))
    agents = result.scalars().all()
    assert len(agents) == 0


@pytest.mark.asyncio
async def test_cascade_delete_agent_removes_capabilities(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    cap = AgentCapability(agent_id=agent.id, capability="purchase")
    db_session.add(cap)
    await db_session.flush()

    await db_session.delete(agent)
    await db_session.flush()

    result = await db_session.execute(select(AgentCapability))
    caps = result.scalars().all()
    assert len(caps) == 0


@pytest.mark.asyncio
async def test_transaction_policy_set_null(db_session: AsyncSession):
    """When a policy is deleted, transaction.policy_id should be SET NULL."""
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    policy = await _create_policy(db_session, user)

    tx = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        policy_id=policy.id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx)
    await db_session.flush()

    await db_session.delete(policy)
    await db_session.flush()

    await db_session.refresh(tx)
    assert tx.policy_id is None


@pytest.mark.asyncio
async def test_decision_policy_set_null(db_session: AsyncSession):
    """When a policy is deleted, decision.policy_id should be SET NULL."""
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)
    policy = await _create_policy(db_session, user)
    tx = Transaction(
        user_id=user.id,
        agent_id=agent.id,
        intent_id=intent.id,
        policy_id=policy.id,
        idempotency_key=uuid.uuid4(),
        transaction_type="purchase",
        amount=100,
    )
    db_session.add(tx)
    await db_session.flush()

    dec = Decision(transaction_id=tx.id, decision="ALLOW", policy_id=policy.id, version=1)
    db_session.add(dec)
    await db_session.flush()

    await db_session.delete(policy)
    await db_session.flush()

    await db_session.refresh(dec)
    assert dec.policy_id is None

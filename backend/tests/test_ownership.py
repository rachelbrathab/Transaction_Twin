"""Tests for ownership validation — cross-table integrity checks."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ownership import validate_agent_belongs_to_user, validate_intent_ownership
from app.models import Agent, Intent, User


async def _create_user(db: AsyncSession, name: str = "User") -> User:
    user = User(display_name=name, status="active")
    db.add(user)
    await db.flush()
    return user


async def _create_agent(db: AsyncSession, user: User, name: str = "Bot") -> Agent:
    agent = Agent(user_id=user.id, name=name, status="active")
    db.add(agent)
    await db.flush()
    return agent


async def _create_intent(db: AsyncSession, user: User, agent: Agent) -> Intent:
    intent = Intent(user_id=user.id, agent_id=agent.id, original_request="test")
    db.add(intent)
    await db.flush()
    return intent


@pytest.mark.asyncio
async def test_validate_agent_belongs_to_user_success(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    # Should not raise
    await validate_agent_belongs_to_user(db_session, user.id, agent.id)


@pytest.mark.asyncio
async def test_validate_agent_belongs_to_user_wrong_user(db_session: AsyncSession):
    user_a = await _create_user(db_session, "Alice")
    user_b = await _create_user(db_session, "Bob")
    agent = await _create_agent(db_session, user_b, "BobBot")

    with pytest.raises(ValueError, match="belongs to user"):
        await validate_agent_belongs_to_user(db_session, user_a.id, agent.id)


@pytest.mark.asyncio
async def test_validate_agent_belongs_to_user_nonexistent(db_session: AsyncSession):
    user = await _create_user(db_session)
    fake_id = uuid.uuid4()

    with pytest.raises(ValueError, match="does not exist"):
        await validate_agent_belongs_to_user(db_session, user.id, fake_id)


@pytest.mark.asyncio
async def test_validate_intent_ownership_success(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)
    intent = await _create_intent(db_session, user, agent)

    await validate_intent_ownership(db_session, user.id, agent.id, intent.id)


@pytest.mark.asyncio
async def test_validate_intent_wrong_user(db_session: AsyncSession):
    user_a = await _create_user(db_session, "Alice")
    user_b = await _create_user(db_session, "Bob")
    agent_a = await _create_agent(db_session, user_a, "AliceBot")
    bob_bot = await _create_agent(db_session, user_b, "BobBot")
    intent_b = await _create_intent(db_session, user_b, bob_bot)

    with pytest.raises(ValueError, match="belongs to user"):
        await validate_intent_ownership(db_session, user_a.id, agent_a.id, intent_b.id)


@pytest.mark.asyncio
async def test_validate_intent_wrong_agent(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent_a = await _create_agent(db_session, user, "Bot1")
    agent_b = await _create_agent(db_session, user, "Bot2")
    intent = await _create_intent(db_session, user, agent_a)

    with pytest.raises(ValueError, match="created for agent"):
        await validate_intent_ownership(db_session, user.id, agent_b.id, intent.id)


@pytest.mark.asyncio
async def test_validate_intent_nonexistent(db_session: AsyncSession):
    user = await _create_user(db_session)
    agent = await _create_agent(db_session, user)

    with pytest.raises(ValueError, match="does not exist"):
        await validate_intent_ownership(db_session, user.id, agent.id, uuid.uuid4())

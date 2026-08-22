"""Tests for IntentEngine orchestrator — full pipeline integration."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.user import User
from app.services.intent_engine.adapters.deterministic import DeterministicAdapter
from app.services.intent_engine.engine import IntentEngine
from app.services.intent_engine.models import IntentParseRequest, ParseStatus


async def _create_user_agent(db: AsyncSession) -> tuple[User, Agent]:
    user = User(display_name="Test User", status="active")
    db.add(user)
    await db.flush()
    agent = Agent(user_id=user.id, name="Test Agent", status="active")
    db.add(agent)
    await db.flush()
    return user, agent


@pytest.fixture
def engine():
    return IntentEngine(adapters=[DeterministicAdapter()])


class TestIntentEnginePipeline:
    @pytest.mark.asyncio
    async def test_successful_parse(self, engine, db_session):
        user, agent = await _create_user_agent(db_session)
        request = IntentParseRequest(
            user_id=str(user.id),
            agent_id=str(agent.id),
            original_request="Buy black running shoes under ₹4,000",
            default_currency="INR",
        )
        result = await engine.parse(request, db_session)
        assert result.status == ParseStatus.PARSED
        assert result.intent_id is not None
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_structured_intent_populated(self, engine, db_session):
        user, agent = await _create_user_agent(db_session)
        request = IntentParseRequest(
            user_id=str(user.id),
            agent_id=str(agent.id),
            original_request="Buy black running shoes under ₹4,000",
            default_currency="INR",
        )
        result = await engine.parse(request, db_session)
        assert result.structured_intent is not None
        assert result.structured_intent.goal.value == "purchase"
        assert result.structured_intent.amount.max == 4000.0

    @pytest.mark.asyncio
    async def test_original_request_preserved(self, engine, db_session):
        user, agent = await _create_user_agent(db_session)
        original = "Buy black running shoes under ₹4,000"
        request = IntentParseRequest(
            user_id=str(user.id),
            agent_id=str(agent.id),
            original_request=original,
            default_currency="INR",
        )
        result = await engine.parse(request, db_session)
        from app.models.intent import Intent

        intent = await db_session.get(Intent, uuid.UUID(result.intent_id))
        assert intent.original_request == original

    @pytest.mark.asyncio
    async def test_ownership_validation_rejects(self, engine, db_session):
        user_a, agent_a = await _create_user_agent(db_session)
        user_b, agent_b = await _create_user_agent(db_session)
        request = IntentParseRequest(
            user_id=str(user_a.id),
            agent_id=str(agent_b.id),
            original_request="Buy shoes",
            default_currency="INR",
        )
        result = await engine.parse(request, db_session)
        assert result.status == ParseStatus.REJECTED
        reason = result.rejection_reason.lower()
        assert "ownership" in reason or "agent" in reason

    @pytest.mark.asyncio
    async def test_empty_request_rejected(self, engine, db_session):
        user, agent = await _create_user_agent(db_session)
        # Pydantic validation should catch empty string before engine
        with pytest.raises(Exception):
            IntentParseRequest(
                user_id=str(user.id),
                agent_id=str(agent.id),
                original_request="",
                default_currency="INR",
            )

    @pytest.mark.asyncio
    async def test_ambiguous_booking_needs_clarification(self, engine, db_session):
        user, agent = await _create_user_agent(db_session)
        request = IntentParseRequest(
            user_id=str(user.id),
            agent_id=str(agent.id),
            original_request="Book me a good hotel",
            default_currency="INR",
        )
        result = await engine.parse(request, db_session)
        assert result.status in (ParseStatus.PARSED, ParseStatus.NEEDS_CLARIFICATION)
        # Should have ambiguities
        assert len(result.ambiguities) > 0

    @pytest.mark.asyncio
    async def test_trust_merchant_detected(self, engine, db_session):
        user, agent = await _create_user_agent(db_session)
        request = IntentParseRequest(
            user_id=str(user.id),
            agent_id=str(agent.id),
            original_request="Buy shoes from trusted seller under ₹4,000",
            default_currency="INR",
        )
        result = await engine.parse(request, db_session)
        assert result.status == ParseStatus.PARSED
        assert result.structured_intent.merchant_constraints.trust_required is True

    @pytest.mark.asyncio
    async def test_no_payment_authorization(self, engine, db_session):
        """IntentEngine must never execute payments."""
        user, agent = await _create_user_agent(db_session)
        request = IntentParseRequest(
            user_id=str(user.id),
            agent_id=str(agent.id),
            original_request="Buy shoes",
            default_currency="INR",
        )
        result = await engine.parse(request, db_session)
        # Only produces structured intent — no payment execution
        assert result.status in (ParseStatus.PARSED, ParseStatus.NEEDS_CLARIFICATION)

    @pytest.mark.asyncio
    async def test_authorization_scope_null(self, engine, db_session):
        user, agent = await _create_user_agent(db_session)
        request = IntentParseRequest(
            user_id=str(user.id),
            agent_id=str(agent.id),
            original_request="Buy shoes under ₹4,000",
            default_currency="INR",
        )
        result = await engine.parse(request, db_session)
        if result.structured_intent:
            assert result.structured_intent.authorization_scope.value is None

    @pytest.mark.asyncio
    async def test_persistence_survives_session_completion(self, db_engine):
        """Prove intent persists after session commit and close.

        Simulates the get_db() lifecycle:
        1. Parse intent → db.flush()
        2. Session commits (get_db auto-commit)
        3. Session closes
        4. New session opens
        5. Intent is queryable
        """
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.models.intent import Intent

        factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )

        intent_id = None

        # Phase 1: Parse and commit (simulates get_db lifecycle)
        async with factory() as session:
            user, agent = await _create_user_agent(session)
            engine = IntentEngine(adapters=[DeterministicAdapter()])
            request = IntentParseRequest(
                user_id=str(user.id),
                agent_id=str(agent.id),
                original_request="Buy black running shoes under ₹4,000",
                default_currency="INR",
            )
            result = await engine.parse(request, session)
            assert result.status == ParseStatus.PARSED
            intent_id = result.intent_id

            # Simulate get_db() auto-commit
            await session.commit()

        # Phase 2: Fresh session — query the intent
        async with factory() as session:
            intent = await session.get(Intent, uuid.UUID(intent_id))
            assert intent is not None, (
                f"Intent {intent_id} not found after session commit+close"
            )
            assert intent.original_request == "Buy black running shoes under ₹4,000"
            assert intent.status == "active"
            assert intent.confidence is not None
            assert intent.confidence > 0

"""Tests for cross-user ownership validation in outcome, review, and history endpoints.

Verifies that User A cannot access, modify, or view transactions belonging to User B.

Strategy: All tests use the TestClient which shares the app's database engine.
Test data is created via the app's own get_db session to ensure visibility.
Authentication is provided via JWT tokens in the Authorization header.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import create_access_token
from app.core.database import Base, get_db
from app.core.identity import get_current_user
from app.main import app


def _auth_headers(user_id: str) -> dict[str, str]:
    """Create Authorization headers for a given user ID."""
    token = create_access_token(uuid.UUID(user_id))
    return {"Authorization": f"Bearer {token}"}


def _make_user_override(user_id: str, session_factory):
    """Create a get_current_user override that returns a specific user from the DB."""

    async def _override():
        from sqlalchemy import select as sa_select

        from app.models.user import User

        async with session_factory() as session:
            result = await session.execute(
                sa_select(User).where(User.id == uuid.UUID(user_id))
            )
            user = result.scalar_one_or_none()
            if user is None:
                raise RuntimeError(f"Test user {user_id} not found in database")
            return user

    return _override


async def _create_test_data(session: AsyncSession):
    """Create User A, User B, agents, intents, transactions in a single session."""
    from app.models.agent import Agent
    from app.models.decision import Decision
    from app.models.intent import Intent
    from app.models.transaction import Transaction
    from app.models.transaction_event import TransactionEvent
    from app.models.user import User

    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    agent_a_id = uuid.uuid4()
    agent_b_id = uuid.uuid4()
    intent_a_id = uuid.uuid4()
    intent_b_id = uuid.uuid4()
    txn_a_id = uuid.uuid4()
    txn_b_id = uuid.uuid4()

    user_a = User(id=user_a_id, display_name="User A")
    user_b = User(id=user_b_id, display_name="User B")
    session.add_all([user_a, user_b])

    agent_a = Agent(id=agent_a_id, user_id=user_a_id, name="Agent A")
    agent_b = Agent(id=agent_b_id, user_id=user_b_id, name="Agent B")
    session.add_all([agent_a, agent_b])

    intent_a = Intent(
        id=intent_a_id, user_id=user_a_id, agent_id=agent_a_id,
        original_request="test a", status="active", currency="INR",
    )
    intent_b = Intent(
        id=intent_b_id, user_id=user_b_id, agent_id=agent_b_id,
        original_request="test b", status="active", currency="INR",
    )
    session.add_all([intent_a, intent_b])

    txn_a = Transaction(
        id=txn_a_id, user_id=user_a_id, agent_id=agent_a_id,
        intent_id=intent_a_id, idempotency_key=uuid.uuid4(),
        transaction_type="purchase", amount=100.00, currency="INR",
        status="decided",
    )
    txn_b = Transaction(
        id=txn_b_id, user_id=user_b_id, agent_id=agent_b_id,
        intent_id=intent_b_id, idempotency_key=uuid.uuid4(),
        transaction_type="purchase", amount=200.00, currency="INR",
        status="decided",
    )
    session.add_all([txn_a, txn_b])

    # REVIEW transaction for User B (for review tests)
    txn_b_review_id = uuid.uuid4()
    txn_b_review = Transaction(
        id=txn_b_review_id, user_id=user_b_id, agent_id=agent_b_id,
        intent_id=intent_b_id, idempotency_key=uuid.uuid4(),
        transaction_type="purchase", amount=500.00, currency="INR",
        status="decided",
    )
    session.add(txn_b_review)
    await session.flush()

    decision = Decision(
        transaction_id=txn_b_review_id, policy_id=None,
        decision="review", reason="Test review", version=1,
    )
    session.add(decision)

    event = TransactionEvent(
        transaction_id=txn_b_review_id, agent_id=agent_b_id,
        sequence_number=1, event_type="decision_created",
        source="system", verification_state="verified",
    )
    session.add(event)
    await session.flush()

    return {
        "user_a_id": str(user_a_id),
        "user_b_id": str(user_b_id),
        "txn_a_id": str(txn_a_id),
        "txn_b_id": str(txn_b_id),
        "txn_b_review_id": str(txn_b_review_id),
    }


def _setup_overrides(session_factory):
    """Set up get_db override and return helper to also override get_current_user."""

    async def _override_get_db():
        async with session_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    def set_auth(user_id: str):
        app.dependency_overrides[get_current_user] = _make_user_override(user_id, session_factory)

    def clear():
        app.dependency_overrides.clear()

    return set_auth, clear


@pytest.mark.asyncio
class TestOutcomeOwnership:
    """POST /transactions/{id}/outcomes ownership validation."""

    async def test_owner_can_submit_own_outcome(self):
        """Owner can submit an outcome for their own transaction."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    f"/transactions/{data['txn_a_id']}/outcomes",
                    json={
                        "event_type": "payment_initiated",
                        "source": "payment_provider",
                        "provider": "test",
                        "external_event_id": "evt-001",
                    },
                )
                assert response.status_code == 200
                body = response.json()
                assert body["transaction_id"] == data["txn_a_id"]
        finally:
            clear()
            await engine.dispose()

    async def test_cross_user_outcome_rejected(self):
        """User A cannot submit an outcome for User B's transaction."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    f"/transactions/{data['txn_b_id']}/outcomes",
                    json={
                        "event_type": "payment_success",
                        "source": "payment_provider",
                        "provider": "test",
                        "external_event_id": "evt-002",
                    },
                )
                assert response.status_code == 403
        finally:
            clear()
            await engine.dispose()

    async def test_cross_user_outcome_no_event_created(self):
        """Failed ownership check must not create any events."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    f"/transactions/{data['txn_b_id']}/outcomes",
                    json={"event_type": "payment_success", "source": "payment_provider"},
                )

            # Verify no events created
            async with session_factory() as verify_session:
                from app.models.transaction_event import TransactionEvent
                result = await verify_session.execute(
                    select(TransactionEvent).where(
                        TransactionEvent.transaction_id == uuid.UUID(data["txn_b_id"])
                    )
                )
                events = result.scalars().all()
                assert len(events) == 0
        finally:
            clear()
            await engine.dispose()

    async def test_cross_user_outcome_no_leak(self):
        """403 response must not contain transaction details."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    f"/transactions/{data['txn_b_id']}/outcomes",
                    json={"event_type": "payment_success", "source": "payment_provider"},
                )
                assert response.status_code == 403
                body_str = str(response.json())
                assert data["txn_b_id"] not in body_str
        finally:
            clear()
            await engine.dispose()

    async def test_nonexistent_transaction_404(self):
        """Nonexistent transaction returns 404."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                fake_id = str(uuid.uuid4())
                response = await client.post(
                    f"/transactions/{fake_id}/outcomes",
                    json={"event_type": "payment_success", "source": "payment_provider"},
                )
                assert response.status_code == 404
        finally:
            clear()
            await engine.dispose()

    async def test_unauthenticated_rejected(self):
        """Endpoint requires authentication."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        async def _override_get_db():
            async with session_factory() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[get_db] = _override_get_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    f"/transactions/{data['txn_a_id']}/outcomes",
                    json={"event_type": "payment_success", "source": "payment_provider"},
                )
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


@pytest.mark.asyncio
class TestReviewOwnership:
    """POST /transactions/{id}/review ownership validation."""

    async def test_owner_can_review_own_transaction(self):
        """Owner can review their own REVIEW transaction."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_b_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    f"/transactions/{data['txn_b_review_id']}/review",
                    json={"action": "approve", "reason": "Looks good", "actor_id": "reviewer-1"},
                )
                assert response.status_code == 200
                body = response.json()
                assert body["action"] == "approve"
                assert body["override_status"] == "approved"
        finally:
            clear()
            await engine.dispose()

    async def test_cross_user_review_rejected(self):
        """User A cannot review User B's REVIEW transaction."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    f"/transactions/{data['txn_b_review_id']}/review",
                    json={"action": "approve", "reason": "Unauthorized"},
                )
                assert response.status_code == 403
        finally:
            clear()
            await engine.dispose()

    async def test_cross_user_review_no_override(self):
        """Failed ownership check must not modify the decision."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    f"/transactions/{data['txn_b_review_id']}/review",
                    json={"action": "approve", "reason": "Unauthorized"},
                )

            # Verify decision unchanged
            async with session_factory() as verify_session:
                from app.models.decision import Decision
                result = await verify_session.execute(
                    select(Decision).where(
                        Decision.transaction_id == uuid.UUID(data["txn_b_review_id"])
                    )
                )
                decision = result.scalar_one()
                assert decision.override_status is None
        finally:
            clear()
            await engine.dispose()

    async def test_cross_user_review_no_status_change(self):
        """Failed ownership check must not change transaction status."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    f"/transactions/{data['txn_b_review_id']}/review",
                    json={"action": "approve"},
                )

            # Verify transaction status unchanged
            async with session_factory() as verify_session:
                from app.models.transaction import Transaction
                result = await verify_session.execute(
                    select(Transaction).where(Transaction.id == uuid.UUID(data["txn_b_review_id"]))
                )
                txn = result.scalar_one()
                assert txn.status == "decided"
        finally:
            clear()
            await engine.dispose()


@pytest.mark.asyncio
class TestHistoryOwnership:
    """GET /transactions/{id}/history ownership validation."""

    async def test_owner_can_view_own_history(self):
        """Owner can view their own transaction history."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    f"/transactions/{data['txn_a_id']}/history",
                )
                assert response.status_code == 200
                body = response.json()
                assert body["transaction_id"] == data["txn_a_id"]
        finally:
            clear()
            await engine.dispose()

    async def test_cross_user_history_rejected(self):
        """User A cannot view User B's transaction history."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    f"/transactions/{data['txn_b_id']}/history",
                )
                assert response.status_code == 403
        finally:
            clear()
            await engine.dispose()

    async def test_cross_user_history_no_details(self):
        """403 response must not leak transaction details."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    f"/transactions/{data['txn_b_id']}/history",
                )
                assert response.status_code == 403
                body_str = str(response.json())
                assert data["txn_b_id"] not in body_str
        finally:
            clear()
            await engine.dispose()

    async def test_nonexistent_transaction_404(self):
        """Nonexistent transaction returns 404."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        set_auth, clear = _setup_overrides(session_factory)
        try:
            set_auth(data["user_a_id"])
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                fake_id = str(uuid.uuid4())
                response = await client.get(
                    f"/transactions/{fake_id}/history",
                )
                assert response.status_code == 404
        finally:
            clear()
            await engine.dispose()

    async def test_unauthenticated_rejected(self):
        """Endpoint requires authentication."""
        engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            data = await _create_test_data(session)
            await session.commit()

        async def _override_get_db():
            async with session_factory() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[get_db] = _override_get_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    f"/transactions/{data['txn_a_id']}/history",
                )
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

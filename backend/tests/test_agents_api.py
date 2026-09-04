"""Tests for Agent management endpoints.

Verifies:
- Agent creation with authenticated user
- Agent listing scoped to authenticated user
- Agent detail retrieval with ownership enforcement
- Agent update with ownership enforcement
- Unauthenticated access rejection
- Cross-user ownership isolation
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import create_access_token
from app.core.database import Base, get_db
from app.core.rate_limit import clear_rate_limiter
from app.main import app


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Ensure dependency overrides and rate limiter are cleared after every test."""
    clear_rate_limiter()
    yield
    app.dependency_overrides.clear()
    clear_rate_limiter()


def _make_engine_and_factory():
    """Create a fresh in-memory SQLite engine and session factory."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _setup_db_override(factory):
    """Override get_db to use the given factory."""

    async def _override_get_db():
        async with factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db


async def _create_tables(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    """Create an Authorization header for the given user_id."""
    token = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
class TestCreateAgent:
    """POST /api/v1/agents"""

    async def test_create_agent_success(self):
        """Authenticated user can create an agent."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_id = uuid.uuid4()
        try:
            # Create user directly
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_id, display_name="Test User"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/agents",
                    json={"name": "Payment Agent", "description": "Handles payments"},
                    headers=_auth_header(user_id),
                )
                assert response.status_code == 201
                body = response.json()
                assert body["name"] == "Payment Agent"
                assert body["description"] == "Handles payments"
                assert body["user_id"] == str(user_id)
                assert body["status"] == "active"
                assert "id" in body
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_create_agent_minimal(self):
        """Agent can be created with just a name."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_id = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_id, display_name="Test User"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/agents",
                    json={"name": "Minimal Agent"},
                    headers=_auth_header(user_id),
                )
                assert response.status_code == 201
                body = response.json()
                assert body["name"] == "Minimal Agent"
                assert body["description"] is None
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_create_agent_empty_name_rejected(self):
        """Empty agent name is rejected."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_id = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_id, display_name="Test User"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/agents",
                    json={"name": ""},
                    headers=_auth_header(user_id),
                )
                assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_create_agent_unauthenticated(self):
        """Unauthenticated request returns 401."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/agents",
                    json={"name": "No Auth Agent"},
                )
                assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


@pytest.mark.asyncio
class TestListAgents:
    """GET /api/v1/agents"""

    async def test_list_agents_empty(self):
        """New user gets an empty agent list."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_id = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_id, display_name="Test User"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/agents",
                    headers=_auth_header(user_id),
                )
                assert response.status_code == 200
                body = response.json()
                assert body["agents"] == []
                assert body["total"] == 0
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_list_agents_with_data(self):
        """List returns agents created by the user."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_id = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_id, display_name="Test User"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Create two agents
                await client.post(
                    "/api/v1/agents",
                    json={"name": "Agent A"},
                    headers=_auth_header(user_id),
                )
                await client.post(
                    "/api/v1/agents",
                    json={"name": "Agent B"},
                    headers=_auth_header(user_id),
                )

                response = await client.get(
                    "/api/v1/agents",
                    headers=_auth_header(user_id),
                )
                assert response.status_code == 200
                body = response.json()
                assert body["total"] == 2
                assert len(body["agents"]) == 2
                names = {a["name"] for a in body["agents"]}
                assert names == {"Agent A", "Agent B"}
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_list_agents_isolation(self):
        """Users can only see their own agents."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_a, display_name="User A"))
                session.add(User(id=user_b, display_name="User B"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # User A creates an agent
                await client.post(
                    "/api/v1/agents",
                    json={"name": "A's Agent"},
                    headers=_auth_header(user_a),
                )

                # User B should see empty list
                response = await client.get(
                    "/api/v1/agents",
                    headers=_auth_header(user_b),
                )
                assert response.status_code == 200
                body = response.json()
                assert body["total"] == 0
                assert body["agents"] == []
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


@pytest.mark.asyncio
class TestGetAgent:
    """GET /api/v1/agents/{agent_id}"""

    async def test_get_agent_success(self):
        """User can get their own agent by ID."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_id = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_id, display_name="Test User"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post(
                    "/api/v1/agents",
                    json={"name": "My Agent"},
                    headers=_auth_header(user_id),
                )
                agent_id = create_resp.json()["id"]

                response = await client.get(
                    f"/api/v1/agents/{agent_id}",
                    headers=_auth_header(user_id),
                )
                assert response.status_code == 200
                body = response.json()
                assert body["name"] == "My Agent"
                assert body["id"] == agent_id
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_get_agent_not_found(self):
        """Nonexistent agent ID returns 404."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_id = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_id, display_name="Test User"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                fake_id = str(uuid.uuid4())
                response = await client.get(
                    f"/api/v1/agents/{fake_id}",
                    headers=_auth_header(user_id),
                )
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_get_agent_cross_user_rejected(self):
        """User cannot access another user's agent."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_a, display_name="User A"))
                session.add(User(id=user_b, display_name="User B"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # User A creates an agent
                create_resp = await client.post(
                    "/api/v1/agents",
                    json={"name": "A's Agent"},
                    headers=_auth_header(user_a),
                )
                agent_id = create_resp.json()["id"]

                # User B tries to access it
                response = await client.get(
                    f"/api/v1/agents/{agent_id}",
                    headers=_auth_header(user_b),
                )
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


@pytest.mark.asyncio
class TestUpdateAgent:
    """PUT /api/v1/agents/{agent_id}"""

    async def test_update_agent_name(self):
        """User can update their agent's name."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_id = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_id, display_name="Test User"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post(
                    "/api/v1/agents",
                    json={"name": "Old Name"},
                    headers=_auth_header(user_id),
                )
                agent_id = create_resp.json()["id"]

                response = await client.put(
                    f"/api/v1/agents/{agent_id}",
                    json={"name": "New Name"},
                    headers=_auth_header(user_id),
                )
                assert response.status_code == 200
                body = response.json()
                assert body["name"] == "New Name"
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_update_agent_status(self):
        """User can update their agent's status."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_id = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_id, display_name="Test User"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post(
                    "/api/v1/agents",
                    json={"name": "Status Agent"},
                    headers=_auth_header(user_id),
                )
                agent_id = create_resp.json()["id"]

                response = await client.put(
                    f"/api/v1/agents/{agent_id}",
                    json={"status": "suspended"},
                    headers=_auth_header(user_id),
                )
                assert response.status_code == 200
                body = response.json()
                assert body["status"] == "suspended"
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_update_agent_cross_user_rejected(self):
        """User cannot update another user's agent."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_a, display_name="User A"))
                session.add(User(id=user_b, display_name="User B"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post(
                    "/api/v1/agents",
                    json={"name": "A's Agent"},
                    headers=_auth_header(user_a),
                )
                agent_id = create_resp.json()["id"]

                response = await client.put(
                    f"/api/v1/agents/{agent_id}",
                    json={"name": "Hijacked"},
                    headers=_auth_header(user_b),
                )
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    async def test_update_agent_invalid_status_rejected(self):
        """Invalid status value is rejected."""
        engine, factory = _make_engine_and_factory()
        await _create_tables(engine)
        _setup_db_override(factory)
        user_id = uuid.uuid4()
        try:
            async with factory() as session:
                from app.models.user import User

                session.add(User(id=user_id, display_name="Test User"))
                await session.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post(
                    "/api/v1/agents",
                    json={"name": "Status Agent"},
                    headers=_auth_header(user_id),
                )
                agent_id = create_resp.json()["id"]

                response = await client.put(
                    f"/api/v1/agents/{agent_id}",
                    json={"status": "invalid_status"},
                    headers=_auth_header(user_id),
                )
                assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

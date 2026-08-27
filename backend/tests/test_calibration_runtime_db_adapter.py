"""Calibration Runtime — DB adapter and integration tests.

Uses in-memory aiosqlite with StaticPool for async testing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.calibration_version import CalibrationVersionRecord

# ── Helpers ──────────────────────────────────────────────────────


async def _setup_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _teardown_engine(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _create_version(session, user_id=None, version_id="calibration-v-test",
                    status="generated", param_snapshot=None, **kwargs):
    """Create a CalibrationVersionRecord."""
    version = CalibrationVersionRecord(
        user_id=user_id or uuid.uuid4(),
        version_id=version_id,
        source_window_days=kwargs.get("source_window_days", 30),
        total_samples=kwargs.get("total_samples", 100),
        eligible_samples=kwargs.get("eligible_samples", 80),
        excluded_samples=kwargs.get("excluded_samples", 20),
        recommendation_count=kwargs.get("recommendation_count", 3),
        parameter_snapshot=param_snapshot or {},
        status=status,
        activated_at=kwargs.get("activated_at"),
        activated_by=kwargs.get("activated_by"),
        previous_version=kwargs.get("previous_version"),
    )
    session.add(version)
    return version


# ── DB Adapter Tests ─────────────────────────────────────────────


@pytest.mark.asyncio
class TestLoadActiveCalibration:
    async def test_returns_none_when_no_active(self):
        from app.services.calibration_runtime.db_adapter import (
            load_active_calibration,
        )

        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                _create_version(session, user_id=user_id, status="generated")
                await session.commit()

            async with factory() as session:
                result = await load_active_calibration(session, user_id)
                assert result is None
        finally:
            await _teardown_engine(engine)

    async def test_returns_active_version(self):
        from app.services.calibration_runtime.db_adapter import (
            load_active_calibration,
        )

        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                _create_version(
                    session,
                    user_id=user_id,
                    version_id="calibration-v-active",
                    status="active",
                    param_snapshot={"signal_weights": {"intent_drift": 0.30}},
                    activated_at=datetime.now(UTC),
                )
                await session.commit()

            async with factory() as session:
                result = await load_active_calibration(session, user_id)
                assert result is not None
                assert result.is_active is True
                assert result.version_id == "calibration-v-active"
                assert result.parameter_snapshot == {
                    "signal_weights": {"intent_drift": 0.30},
                }
        finally:
            await _teardown_engine(engine)

    async def test_scoped_by_user_id(self):
        from app.services.calibration_runtime.db_adapter import (
            load_active_calibration,
        )

        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_a = uuid.uuid4()
            user_b = uuid.uuid4()
            async with factory() as session:
                _create_version(
                    session, user_id=user_a, status="active",
                    version_id="calibration-v-a",
                    activated_at=datetime.now(UTC),
                )
                _create_version(
                    session, user_id=user_b, status="active",
                    version_id="calibration-v-b",
                    activated_at=datetime.now(UTC),
                )
                await session.commit()

            async with factory() as session:
                result_a = await load_active_calibration(session, user_a)
                result_b = await load_active_calibration(session, user_b)
                assert result_a is not None
                assert result_b is not None
                assert result_a.version_id != result_b.version_id
        finally:
            await _teardown_engine(engine)

    async def test_returns_none_for_unknown_user(self):
        from app.services.calibration_runtime.db_adapter import (
            load_active_calibration,
        )

        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            async with factory() as session:
                result = await load_active_calibration(session, uuid.uuid4())
                assert result is None
        finally:
            await _teardown_engine(engine)

    async def test_multiple_active_versions_returns_none(self):
        """Data integrity issue — should fail safely."""
        from app.services.calibration_runtime.db_adapter import (
            load_active_calibration,
        )

        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                _create_version(
                    session, user_id=user_id,
                    version_id="calibration-v1", status="active",
                    activated_at=datetime.now(UTC),
                )
                _create_version(
                    session, user_id=user_id,
                    version_id="calibration-v2", status="active",
                    activated_at=datetime.now(UTC),
                )
                await session.commit()

            async with factory() as session:
                result = await load_active_calibration(session, user_id)
                assert result is None
        finally:
            await _teardown_engine(engine)

    async def test_superseded_version_not_loaded(self):
        from app.services.calibration_runtime.db_adapter import (
            load_active_calibration,
        )

        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                _create_version(
                    session, user_id=user_id, status="superseded",
                    version_id="calibration-v-old",
                )
                await session.commit()

            async with factory() as session:
                result = await load_active_calibration(session, user_id)
                assert result is None
        finally:
            await _teardown_engine(engine)


@pytest.mark.asyncio
class TestLoadCalibrationVersionById:
    async def test_returns_version_when_found(self):
        from app.services.calibration_runtime.db_adapter import (
            load_calibration_version_by_id,
        )

        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                _create_version(
                    session,
                    user_id=user_id,
                    version_id="calibration-v1",
                    status="active",
                )
                await session.commit()

            async with factory() as session:
                result = await load_calibration_version_by_id(
                    session, user_id, "calibration-v1",
                )
                assert result is not None
                assert result.version_id == "calibration-v1"
                assert result.is_active is True
        finally:
            await _teardown_engine(engine)

    async def test_returns_none_when_not_found(self):
        from app.services.calibration_runtime.db_adapter import (
            load_calibration_version_by_id,
        )

        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            async with factory() as session:
                result = await load_calibration_version_by_id(
                    session, uuid.uuid4(), "calibration-nonexistent",
                )
                assert result is None
        finally:
            await _teardown_engine(engine)

    async def test_cross_user_access_returns_none(self):
        from app.services.calibration_runtime.db_adapter import (
            load_calibration_version_by_id,
        )

        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_a = uuid.uuid4()
            user_b = uuid.uuid4()
            async with factory() as session:
                _create_version(
                    session, user_id=user_a, version_id="calibration-v1",
                )
                await session.commit()

            async with factory() as session:
                result = await load_calibration_version_by_id(
                    session, user_b, "calibration-v1",
                )
                assert result is None
        finally:
            await _teardown_engine(engine)


# ── API Integration Tests ────────────────────────────────────────


@pytest.mark.asyncio
class TestRuntimeConfigEndpoint:
    """Test the runtime configuration resolution endpoint."""

    async def test_get_effective_config_no_calibration(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            async def _override_get_db():
                async with factory() as session:
                    yield session

            app.dependency_overrides[get_db] = _override_get_db
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as client:
                resp = await client.get(
                    "/analytics/calibration/effective-config",
                    params={"user_id": str(uuid.uuid4())},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["calibration_active"] is False
                assert "signal_weights" in data
                assert data["validation_passed"] is True
        finally:
            app.dependency_overrides.clear()
            await _teardown_engine(engine)

    async def test_get_effective_config_with_active(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                _create_version(
                    session,
                    user_id=user_id,
                    version_id="calibration-v-calibrated",
                    status="active",
                    param_snapshot={"signal_weights": {"intent_drift": 0.35}},
                    activated_at=datetime.now(UTC),
                )
                await session.commit()

            async def _override_get_db():
                async with factory() as session:
                    yield session

            app.dependency_overrides[get_db] = _override_get_db
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as client:
                resp = await client.get(
                    "/analytics/calibration/effective-config",
                    params={"user_id": str(user_id)},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["calibration_active"] is True
                assert data["source_version_id"] == "calibration-v-calibrated"
                assert data["signal_weights"]["intent_drift"] == 0.35
                assert data["validation_passed"] is True
        finally:
            app.dependency_overrides.clear()
            await _teardown_engine(engine)

    async def test_requires_user_id(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            async def _override_get_db():
                async with factory() as session:
                    yield session

            app.dependency_overrides[get_db] = _override_get_db
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as client:
                resp = await client.get(
                    "/analytics/calibration/effective-config",
                )
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()
            await _teardown_engine(engine)

    async def test_cross_user_cannot_see_config(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_a = uuid.uuid4()
            user_b = uuid.uuid4()
            async with factory() as session:
                _create_version(
                    session,
                    user_id=user_b,
                    version_id="calibration-v-secret",
                    status="active",
                    param_snapshot={"signal_weights": {"intent_drift": 0.99}},
                    activated_at=datetime.now(UTC),
                )
                await session.commit()

            async def _override_get_db():
                async with factory() as session:
                    yield session

            app.dependency_overrides[get_db] = _override_get_db
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as client:
                # User A should see defaults, not User B's calibration
                resp = await client.get(
                    "/analytics/calibration/effective-config",
                    params={"user_id": str(user_a)},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["calibration_active"] is False
                # Default, not User B's 0.99
                assert data["signal_weights"]["intent_drift"] == 0.25
        finally:
            app.dependency_overrides.clear()
            await _teardown_engine(engine)

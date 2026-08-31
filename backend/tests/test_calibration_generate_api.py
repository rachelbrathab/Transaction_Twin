"""Tests for Calibration Intelligence generate, list, and detail endpoints.

Covers:
- Generate endpoint (idempotency, ownership, empty data)
- Version listing (ownership, filtering)
- Version detail (ownership, 404)
- Recommendation detail (ownership, 404)
- Security (cross-user, no runtime mutation)
"""

import uuid

import pytest
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
from app.models.calibration_recommendation import (
    CalibrationRecommendationRecord,
)
from app.models.calibration_version import CalibrationVersionRecord

USER_A = uuid.uuid4()
USER_B = uuid.uuid4()

_active_user_id: uuid.UUID = USER_A


class _FakeUser:
    def __init__(self, uid: uuid.UUID) -> None:
        self.id = uid


async def _override_get_current_user():
    return _FakeUser(_active_user_id)


async def _make_client(engine):
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

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
    return client, factory


async def _cleanup():
    app.dependency_overrides.clear()


async def _create_version(
    session: AsyncSession,
    version_id: str = "test-v1",
    user_id: uuid.UUID = USER_A,
    status: str = "generated",
) -> CalibrationVersionRecord:
    ver = CalibrationVersionRecord(
        user_id=user_id,
        version_id=version_id,
        source_window_days=30,
        total_samples=10,
        eligible_samples=8,
        excluded_samples=2,
        recommendation_count=0,
        status=status,
    )
    session.add(ver)
    await session.flush()
    return ver


async def _create_recommendation(
    session: AsyncSession,
    version_id: str = "test-v1",
    user_id: uuid.UUID = USER_A,
    status: str = "generated",
) -> CalibrationRecommendationRecord:
    rec = CalibrationRecommendationRecord(
        id=uuid.uuid4(),
        user_id=user_id,
        recommendation_type="weight_review",
        engine="risk_engine",
        parameter="test_param",
        rationale="Test rationale",
        calibration_version=version_id,
        status=status,
        evidence={},
    )
    session.add(rec)
    await session.flush()
    return rec


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


# ══════════════════════════════════════════════════════════════
# GENERATE ENDPOINT
# ══════════════════════════════════════════════════════════════


class TestGenerateEndpoint:
    @pytest.mark.asyncio
    async def test_generate_missing_identity(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            app.dependency_overrides.pop(get_current_user, None)
            resp = await client.post(
                "/api/v1/analytics/calibration/generate",
                json={"window_days": 30},
            )
            assert resp.status_code == 401
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_generate_no_transactions(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.post(
                "/api/v1/analytics/calibration/generate",

                json={"window_days": 30},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["version_id"] == ""
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# VERSION LISTING
# ══════════════════════════════════════════════════════════════


class TestVersionListing:
    @pytest.mark.asyncio
    async def test_list_versions_missing_identity(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            app.dependency_overrides.pop(get_current_user, None)
            resp = await client.get(
                "/api/v1/analytics/calibration/versions",
            )
            assert resp.status_code == 401
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_list_versions_empty(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.get(
                "/api/v1/analytics/calibration/versions",

            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
            assert data["versions"] == []
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_list_versions_with_data(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_version(session, version_id="v1")
                await _create_version(
                    session, version_id="v2", status="active",
                )
                await session.commit()

            resp = await client.get(
                "/api/v1/analytics/calibration/versions",

            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_list_versions_filters_by_user(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_version(
                    session, version_id="v1", user_id=USER_A,
                )
                await _create_version(
                    session, version_id="v2", user_id=USER_B,
                )
                await session.commit()

            resp = await client.get(
                "/api/v1/analytics/calibration/versions",

            )
            data = resp.json()
            assert data["total"] == 1
            assert data["versions"][0]["version_id"] == "v1"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_list_versions_status_filter(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_version(
                    session, version_id="v1", status="generated",
                )
                await _create_version(
                    session, version_id="v2", status="active",
                )
                await session.commit()

            resp = await client.get(
                "/api/v1/analytics/calibration/versions",
                params={
                    "user_id": str(USER_A),
                    "status": "active",
                },
            )
            data = resp.json()
            assert data["total"] == 1
            assert data["versions"][0]["status"] == "active"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# VERSION DETAIL
# ══════════════════════════════════════════════════════════════


class TestVersionDetail:
    @pytest.mark.asyncio
    async def test_get_version_not_found(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.get(
                "/api/v1/analytics/calibration/versions/nonexistent",

            )
            assert resp.status_code == 404
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_get_version_with_recommendations(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_version(session, version_id="v1")
                await _create_recommendation(
                    session, version_id="v1",
                )
                await _create_recommendation(
                    session, version_id="v1",
                )
                await session.commit()

            resp = await client.get(
                "/api/v1/analytics/calibration/versions/v1",

            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["version"]["version_id"] == "v1"
            assert len(data["recommendations"]) == 2
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_get_version_cross_user_404(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_version(
                    session,
                    version_id="v1",
                    user_id=USER_A,
                )
                await session.commit()

            # Authenticate as USER_B trying to access USER_A's version
            global _active_user_id
            _active_user_id = USER_B
            resp = await client.get(
                "/api/v1/analytics/calibration/versions/v1",
            )
            assert resp.status_code == 404
        finally:
            _active_user_id = USER_A
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# RECOMMENDATION DETAIL
# ══════════════════════════════════════════════════════════════


class TestRecommendationDetail:
    @pytest.mark.asyncio
    async def test_get_recommendation_not_found(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.get(
                f"/api/v1/analytics/calibration/"
                f"recommendations/{uuid.uuid4()}",

            )
            assert resp.status_code == 404
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_get_recommendation_found(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(session)
                rec_id = str(rec.id)
                await session.commit()

            resp = await client.get(
                f"/api/v1/analytics/calibration/"
                f"recommendations/{rec_id}",

            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["recommendation_id"] == rec_id
            assert data["engine"] == "risk_engine"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_get_recommendation_cross_user_404(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, user_id=USER_A,
                )
                rec_id = str(rec.id)
                await session.commit()

            # Authenticate as USER_B trying to access USER_A's recommendation
            global _active_user_id
            _active_user_id = USER_B
            resp = await client.get(
                f"/api/v1/analytics/calibration/"
                f"recommendations/{rec_id}",
            )
            assert resp.status_code == 404
        finally:
            _active_user_id = USER_A
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# IDEMPOTENCY (API-level)
# ══════════════════════════════════════════════════════════════


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_persistence_returns_existing(self):
        """Persisting the same version_id twice returns existing."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            from app.services.calibration_intelligence.models import (
                CalibrationDataset,
                CalibrationIntelligenceResult,
                CalibrationRecommendation,
                CalibrationVersion,
                DataSufficiencyLevel,
                RecommendationStatus,
                RecommendationType,
            )
            from app.services.calibration_intelligence.persistence import (
                persist_calibration_result,
            )

            version = CalibrationVersion(
                version_id="api-idem-v1",
                source_window_days=30,
                total_samples=10,
                eligible_samples=8,
                excluded_samples=2,
                recommendation_count=1,
                status=RecommendationStatus.GENERATED,
            )
            rec = CalibrationRecommendation(
                recommendation_id="api-rec-1",
                recommendation_type=RecommendationType.WEIGHT_REVIEW,
                engine="risk_engine",
                parameter="test",
                rationale="Test",
                sample_count=10,
                data_sufficiency=DataSufficiencyLevel.MODERATE,
                severity="info",
                calibration_version="api-idem-v1",
            )
            result = CalibrationIntelligenceResult(
                dataset=CalibrationDataset(
                    total_samples=10,
                    eligible_samples=8,
                    excluded_samples=2,
                ),
                recommendations=[rec],
                version=version,
            )

            async with factory() as session:
                pr1 = await persist_calibration_result(
                    session, USER_A, result,
                )
                await session.commit()
                assert pr1.created is True

            async with factory() as session:
                pr2 = await persist_calibration_result(
                    session, USER_A, result,
                )
                await session.commit()
                assert pr2.created is False
                assert pr2.version.id == pr1.version.id
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_list_shows_only_own_versions(self):
        """User A cannot see User B's versions."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_version(
                    session, version_id="v-a1", user_id=USER_A,
                )
                await _create_version(
                    session, version_id="v-b1", user_id=USER_B,
                )
                await session.commit()

            resp_a = await client.get(
                "/api/v1/analytics/calibration/versions",
            )

            # Switch identity to USER_B
            global _active_user_id
            _active_user_id = USER_B
            resp_b = await client.get(
                "/api/v1/analytics/calibration/versions",
            )

            _active_user_id = USER_A
            assert resp_a.json()["total"] == 1
            assert resp_a.json()["versions"][0]["version_id"] == "v-a1"
            assert resp_b.json()["total"] == 1
            assert resp_b.json()["versions"][0]["version_id"] == "v-b1"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# SECURITY
# ══════════════════════════════════════════════════════════════


class TestSecurity:
    def test_generate_no_runtime_mutation(self):
        import inspect

        from app.api.v1.endpoints import calibration_intelligence
        source = inspect.getsource(calibration_intelligence)
        assert "SIGNAL_WEIGHTS[" not in source
        assert "RISK_LEVEL_THRESHOLDS[" not in source
        assert "CONFIDENCE_REDUCTIONS[" not in source

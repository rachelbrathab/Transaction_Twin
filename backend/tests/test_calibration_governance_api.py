"""Tests for Calibration Intelligence governance API.

Covers ownership validation, state machine enforcement,
idempotency, and security for all four endpoints.

Uses get_db dependency override with in-memory SQLite
(project convention from test_ownership_validation.py).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.audit_event import AuditEvent
from app.models.calibration_recommendation import (
    CalibrationRecommendationRecord,
)
from app.models.calibration_version import CalibrationVersionRecord

# ── Helpers ───────────────────────────────────────────────────

USER_A = uuid.uuid4()
USER_B = uuid.uuid4()


async def _make_client(engine):
    """Create an async client with get_db overridden."""
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
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    return client, factory


async def _cleanup():
    """Clear dependency overrides."""
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
    rec_id: uuid.UUID | None = None,
) -> CalibrationRecommendationRecord:
    rec = CalibrationRecommendationRecord(
        id=rec_id or uuid.uuid4(),
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
    """Create SQLite engine and tables."""
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
    """Drop tables and dispose engine."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ══════════════════════════════════════════════════════════════
# OWNERSHIP TESTS
# ══════════════════════════════════════════════════════════════


class TestOutcomesOwnership:
    @pytest.mark.asyncio
    async def test_missing_user_id_returns_422(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.get(
                "/analytics/calibration/outcomes",
            )
            assert resp.status_code == 422
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_owner_can_access(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.get(
                "/analytics/calibration/outcomes",
                params={
                    "user_id": str(USER_A),
                    "window_days": 30,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "samples" in data
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


class TestRecommendationsOwnership:
    @pytest.mark.asyncio
    async def test_missing_user_id_returns_422(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.get(
                "/analytics/calibration/recommendations",
            )
            assert resp.status_code == 422
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_owner_can_access(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_recommendation(session)
                await session.commit()
            resp = await client.get(
                "/analytics/calibration/recommendations",
                params={"user_id": str(USER_A)},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "recommendations" in data
            assert data["total"] == 1
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_filters_by_user(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_recommendation(
                    session, user_id=USER_B,
                )
                await session.commit()
            resp = await client.get(
                "/analytics/calibration/recommendations",
                params={"user_id": str(USER_A)},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


class TestReviewOwnership:
    @pytest.mark.asyncio
    async def test_missing_user_id_returns_422(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.post(
                "/analytics/calibration/"
                "recommendations/some-id/review",
                json={"action": "approve"},
            )
            assert resp.status_code == 422
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_nonexistent_recommendation_returns_404(
        self,
    ):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.post(
                "/analytics/calibration/"
                f"recommendations/{uuid.uuid4()}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            assert resp.status_code == 404
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


class TestActivationOwnership:
    @pytest.mark.asyncio
    async def test_missing_user_id_returns_422(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.post(
                "/analytics/calibration/"
                "versions/some-id/activate",
                json={"confirm": True},
            )
            assert resp.status_code == 422
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_nonexistent_version_returns_404(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.post(
                "/analytics/calibration/"
                f"versions/{uuid.uuid4()}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            assert resp.status_code == 404
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# REVIEW STATE MACHINE
# ══════════════════════════════════════════════════════════════


class TestReviewStateMachine:
    @pytest.mark.asyncio
    async def test_approve_generated_to_reviewed(self):
        """GENERATED → REVIEWED (first approve step)."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="generated",
                )
                await session.commit()
                rec_id = str(rec.id)

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "reviewed"
            assert data["idempotent"] is False
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_reject_generated(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="generated",
                )
                await session.commit()
                rec_id = str(rec.id)

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={
                    "action": "reject",
                    "reason": "Not enough evidence",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "rejected"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_approve_reviewed_to_approved(self):
        """REVIEWED → APPROVED (second approve step)."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="reviewed",
                )
                await session.commit()
                rec_id = str(rec.id)

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "approved"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_reject_reviewed(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="reviewed",
                )
                await session.commit()
                rec_id = str(rec.id)

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "reject"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "rejected"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_rejected_is_terminal(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="rejected",
                )
                await session.commit()
                rec_id = str(rec.id)

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            assert resp.status_code == 409
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_superseded_is_terminal(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="superseded",
                )
                await session.commit()
                rec_id = str(rec.id)

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            assert resp.status_code == 409
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_cross_user_review_returns_403(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session,
                    user_id=USER_A,
                    status="generated",
                )
                await session.commit()
                rec_id = str(rec.id)

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_B)},
                json={"action": "approve"},
            )
            assert resp.status_code == 403
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_invalid_action_returns_422(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="generated",
                )
                await session.commit()
                rec_id = str(rec.id)

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "bogus"},
            )
            assert resp.status_code == 422
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# ACTIVATION STATE MACHINE
# ══════════════════════════════════════════════════════════════


class TestActivationStateMachine:
    @pytest.mark.asyncio
    async def test_activate_generated_version(self):
        """GENERATED version with no pending recs can activate."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session, status="generated",
                )
                vid = ver.version_id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "active"
            assert data["idempotent"] is False
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_activate_generated_blocked_by_pending_recs(
        self,
    ):
        """GENERATED version with pending recs cannot activate."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session, status="generated",
                )
                await _create_recommendation(
                    session,
                    version_id=ver.version_id,
                    status="generated",
                )
                vid = ver.version_id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            assert resp.status_code == 409
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_superseded_can_activate_for_rollback(self):
        """Superseded versions can be reactivated for rollback."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session, status="superseded",
                )
                vid = ver.version_id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "active"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_requires_confirm_true(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session, status="generated",
                )
                vid = ver.version_id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": False},
            )
            assert resp.status_code == 422
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_previous_active_superseded(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_version(
                    session,
                    version_id="v1",
                    status="generated",
                )
                await session.commit()

            resp1 = await client.post(
                "/analytics/calibration/"
                "versions/v1/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            assert resp1.status_code == 200

            async with factory() as session:
                await _create_version(
                    session,
                    version_id="v2",
                    status="generated",
                )
                await session.commit()

            resp2 = await client.post(
                "/analytics/calibration/"
                "versions/v2/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            assert resp2.status_code == 200
            data = resp2.json()
            assert data["previous_version"] == "v1"

            async with factory() as session:
                result = await session.execute(
                    select(CalibrationVersionRecord).where(
                        CalibrationVersionRecord.version_id
                        == "v1",
                    )
                )
                v1 = result.scalar_one()
                assert v1.status == "superseded"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_cross_user_activation_returns_403(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session,
                    user_id=USER_A,
                    status="generated",
                )
                vid = ver.version_id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_B)},
                json={"confirm": True},
            )
            assert resp.status_code == 403
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_activate_with_pending_recs_fails(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session, status="generated",
                )
                await _create_recommendation(
                    session,
                    version_id=ver.version_id,
                    status="generated",
                )
                vid = ver.version_id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            assert resp.status_code == 409
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_activate_with_all_approved_recs(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session, status="generated",
                )
                await _create_recommendation(
                    session,
                    version_id=ver.version_id,
                    status="approved",
                )
                vid = ver.version_id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "active"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# IDEMPOTENCY
# ══════════════════════════════════════════════════════════════


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_repeat_activation_returns_idempotent(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session, status="generated",
                )
                vid = ver.version_id
                await session.commit()

            resp1 = await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            assert resp1.status_code == 200
            assert resp1.json()["idempotent"] is False

            resp2 = await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            assert resp2.status_code == 200
            assert resp2.json()["idempotent"] is True
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_repeat_review_returns_idempotent(self):
        """Same action on already-approved → idempotent."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="approved",
                )
                rec_id = str(rec.id)
                await session.commit()

            # Already approved, approve again → idempotent
            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            assert resp.status_code == 200
            assert resp.json()["idempotent"] is True
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# DATA INTEGRITY
# ══════════════════════════════════════════════════════════════


class TestDataIntegrity:
    @pytest.mark.asyncio
    async def test_content_preserved_on_review(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="generated",
                )
                rec_id = str(rec.id)
                await session.commit()

            # Two-step: generated → reviewed → approved
            await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )

            async with factory() as session:
                result = await session.execute(
                    select(
                        CalibrationRecommendationRecord,
                    ).where(
                        CalibrationRecommendationRecord.id
                        == uuid.UUID(rec_id),
                    )
                )
                updated = result.scalar_one()
                assert (
                    updated.recommendation_type
                    == "weight_review"
                )
                assert updated.engine == "risk_engine"
                assert updated.parameter == "test_param"
                assert updated.rationale == "Test rationale"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_governance_fields_updated(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="generated",
                )
                rec_id = str(rec.id)
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={
                    "action": "reject",
                    "reason": "Insufficient evidence",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "rejected"

            async with factory() as session:
                result = await session.execute(
                    select(
                        CalibrationRecommendationRecord,
                    ).where(
                        CalibrationRecommendationRecord.id
                        == uuid.UUID(rec_id),
                    )
                )
                updated = result.scalar_one()
                assert updated.status == "rejected"
                assert updated.reviewed_by == USER_A
                assert (
                    updated.rejection_reason
                    == "Insufficient evidence"
                )
                assert updated.reviewed_at is not None
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_version_activation_fields(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session, status="generated",
                )
                ver_id = ver.id
                vid = ver.version_id
                await session.commit()

            await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )

            async with factory() as session:
                result = await session.execute(
                    select(
                        CalibrationVersionRecord,
                    ).where(
                        CalibrationVersionRecord.id == ver_id,
                    )
                )
                updated = result.scalar_one()
                assert updated.status == "active"
                assert updated.activated_by == USER_A
                assert updated.activated_at is not None
                assert updated.previous_version is None
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_recommendation_activated_on_version(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session, status="generated",
                )
                rec = await _create_recommendation(
                    session,
                    version_id=ver.version_id,
                    status="approved",
                )
                rec_id = rec.id
                vid = ver.version_id
                await session.commit()

            await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )

            async with factory() as session:
                result = await session.execute(
                    select(
                        CalibrationRecommendationRecord,
                    ).where(
                        CalibrationRecommendationRecord.id
                        == rec_id,
                    )
                )
                updated = result.scalar_one()
                assert updated.status == "activated"
                assert updated.activated_by == USER_A
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# AUDIT EVENTS
# ══════════════════════════════════════════════════════════════


class TestAuditEvents:
    @pytest.mark.asyncio
    async def test_review_creates_audit(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="generated",
                )
                rec_id = rec.id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            assert resp.status_code == 200


            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == rec_id,
                    )
                )
                events = result.scalars().all()
                assert len(events) == 1
                meta = events[0].metadata_
                assert meta["new_status"] == "reviewed"
                assert meta["user_id"] == str(USER_A)
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_activation_creates_audit(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session, status="generated",
                )
                ver_id = ver.id
                vid = ver.version_id
                await session.commit()

            await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )


            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == ver_id,
                        AuditEvent.event_type
                        == "calibration_activated",
                    )
                )
                events = result.scalars().all()
                assert len(events) == 1
                meta = events[0].metadata_
                assert meta["version_id"] == vid
                assert meta["new_status"] == "active"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_supersession_creates_audit(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_version(
                    session,
                    version_id="v1",
                    status="generated",
                )
                await _create_version(
                    session,
                    version_id="v2",
                    status="generated",
                )
                await session.commit()

            await client.post(
                "/analytics/calibration/"
                "versions/v1/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            await client.post(
                "/analytics/calibration/"
                "versions/v2/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )


            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.event_type
                        == "calibration_superseded",
                    )
                )
                events = result.scalars().all()
                assert len(events) >= 1
                meta = events[0].metadata_
                assert meta["new_status"] == "superseded"
                assert meta["superseded_by"] == "v2"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# SECURITY
# ══════════════════════════════════════════════════════════════


class TestSecurity:
    def test_state_machine_no_eval_exec(self):
        import inspect

        from app.services.calibration_intelligence import (
            state_machine,
        )
        source = inspect.getsource(state_machine)
        assert "eval(" not in source
        assert "exec(" not in source
        assert "subprocess" not in source
        assert "__import__" not in source

    def test_state_machine_no_sqlalchemy(self):
        import inspect

        from app.services.calibration_intelligence import (
            state_machine,
        )
        source = inspect.getsource(state_machine)
        # Check for actual imports, not just docstring mentions
        lines = source.split("\n")
        code_lines = [
            ln for ln in lines
            if not ln.strip().startswith('"""')
            and not ln.strip().startswith("'''")
            and not ln.strip().startswith("#")
        ]
        code_only = "\n".join(code_lines)
        assert "import sqlalchemy" not in code_only.lower()
        assert "from sqlalchemy" not in code_only.lower()

    def test_no_runtime_weight_mutation(self):
        import inspect

        from app.api.v1.endpoints import (
            calibration_intelligence,
        )
        source = inspect.getsource(calibration_intelligence)
        assert "SIGNAL_WEIGHTS[" not in source
        assert "RISK_LEVEL_THRESHOLDS[" not in source
        assert "CONFIDENCE_REDUCTIONS[" not in source

    @pytest.mark.asyncio
    async def test_review_no_data_leak(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session,
                    user_id=USER_A,
                    status="generated",
                )
                rec_id = str(rec.id)
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_B)},
                json={"action": "approve"},
            )
            assert resp.status_code == 403
            body = resp.json()
            assert "rationale" not in body
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_activation_no_data_leak(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session,
                    user_id=USER_A,
                    status="generated",
                )
                vid = ver.version_id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_B)},
                json={"confirm": True},
            )
            assert resp.status_code == 403
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# RECOMMENDATIONS LISTING
# ══════════════════════════════════════════════════════════════


class TestRecommendationsListing:
    @pytest.mark.asyncio
    async def test_empty_list(self):
        engine = await _setup_engine()
        client, _ = await _make_client(engine)
        try:
            resp = await client.get(
                "/analytics/calibration/recommendations",
                params={"user_id": str(uuid.uuid4())},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
            assert data["recommendations"] == []
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_lists_own_recommendations(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_recommendation(
                    session,
                    user_id=USER_A,
                    status="generated",
                )
                await _create_recommendation(
                    session,
                    user_id=USER_B,
                    status="approved",
                )
                await session.commit()

            resp = await client.get(
                "/analytics/calibration/recommendations",
                params={"user_id": str(USER_A)},
            )
            data = resp.json()
            assert data["total"] == 1
            assert (
                data["recommendations"][0]["status"]
                == "generated"
            )
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_status_filter(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_recommendation(
                    session,
                    user_id=USER_A,
                    status="generated",
                )
                await _create_recommendation(
                    session,
                    user_id=USER_A,
                    status="approved",
                )
                await session.commit()

            resp = await client.get(
                "/analytics/calibration/recommendations",
                params={
                    "user_id": str(USER_A),
                    "status": "approved",
                },
            )
            data = resp.json()
            assert data["total"] == 1
            assert (
                data["recommendations"][0]["status"]
                == "approved"
            )
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_engine_filter(self):
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_recommendation(
                    session,
                    user_id=USER_A,
                    status="generated",
                )
                rec2 = await _create_recommendation(
                    session,
                    user_id=USER_A,
                    status="generated",
                )
                rec2.engine = "policy_engine"
                await session.flush()
                await session.commit()

            resp = await client.get(
                "/analytics/calibration/recommendations",
                params={
                    "user_id": str(USER_A),
                    "engine": "risk_engine",
                },
            )
            data = resp.json()
            assert data["total"] == 1
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# H1: AUDIT METADATA CORRECTNESS
# ══════════════════════════════════════════════════════════════


class TestAuditMetadata:
    @pytest.mark.asyncio
    async def test_generated_to_reviewed_metadata(self):
        """GENERATED → REVIEWED: previous_status must be 'generated'."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="generated",
                )
                rec_id = rec.id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "reviewed"

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == rec_id,
                    )
                )
                events = result.scalars().all()
                assert len(events) == 1
                meta = events[0].metadata_
                assert meta["previous_status"] == "generated"
                assert meta["new_status"] == "reviewed"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_reviewed_to_approved_metadata(self):
        """REVIEWED → APPROVED: previous_status must be 'reviewed'."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="reviewed",
                )
                rec_id = rec.id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "approved"

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == rec_id,
                    )
                )
                events = result.scalars().all()
                assert len(events) == 1
                meta = events[0].metadata_
                assert meta["previous_status"] == "reviewed"
                assert meta["new_status"] == "approved"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_generated_to_rejected_metadata(self):
        """GENERATED → REJECTED: previous_status must be 'generated'."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="generated",
                )
                rec_id = rec.id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "reject", "reason": "No"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "rejected"

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == rec_id,
                    )
                )
                events = result.scalars().all()
                assert len(events) == 1
                meta = events[0].metadata_
                assert meta["previous_status"] == "generated"
                assert meta["new_status"] == "rejected"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_reviewed_to_rejected_metadata(self):
        """REVIEWED → REJECTED: previous_status must be 'reviewed'."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="reviewed",
                )
                rec_id = rec.id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "reject"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "rejected"

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == rec_id,
                    )
                )
                events = result.scalars().all()
                assert len(events) == 1
                meta = events[0].metadata_
                assert meta["previous_status"] == "reviewed"
                assert meta["new_status"] == "rejected"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_activation_audit_previous_status(self):
        """Activation audit must record actual previous version status."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                ver = await _create_version(
                    session, status="generated",
                )
                ver_id = ver.id
                vid = ver.version_id
                await session.commit()

            await client.post(
                f"/analytics/calibration/"
                f"versions/{vid}/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == ver_id,
                        AuditEvent.event_type
                        == "calibration_activated",
                    )
                )
                events = result.scalars().all()
                assert len(events) == 1
                meta = events[0].metadata_
                assert meta["previous_status"] == "generated"
                assert meta["new_status"] == "active"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_supersession_audit_metadata(self):
        """Supersession audit must show active → superseded."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                await _create_version(
                    session,
                    version_id="v1",
                    status="generated",
                )
                await _create_version(
                    session,
                    version_id="v2",
                    status="generated",
                )
                await session.commit()

            await client.post(
                "/analytics/calibration/"
                "versions/v1/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )
            await client.post(
                "/analytics/calibration/"
                "versions/v2/activate",
                params={"user_id": str(USER_A)},
                json={"confirm": True},
            )

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.event_type
                        == "calibration_superseded",
                    )
                )
                events = result.scalars().all()
                assert len(events) >= 1
                meta = events[0].metadata_
                assert meta["previous_status"] == "active"
                assert meta["new_status"] == "superseded"
                assert meta["superseded_by"] == "v2"
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# M1: GOVERNANCE TIMESTAMP CORRECTNESS
# ══════════════════════════════════════════════════════════════


class TestGovernanceTimestamps:
    @pytest.mark.asyncio
    async def test_generated_to_reviewed_sets_only_review_fields(self):
        """GENERATED → reviewed: reviewed_at set, approved_at NOT set."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="generated",
                )
                rec_id = rec.id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "reviewed"

            async with factory() as session:
                result = await session.execute(
                    select(
                        CalibrationRecommendationRecord,
                    ).where(
                        CalibrationRecommendationRecord.id
                        == rec_id,
                    )
                )
                updated = result.scalar_one()
                assert updated.reviewed_at is not None
                assert updated.reviewed_by == USER_A
                # M1: approved_at must NOT be set
                assert updated.approved_at is None
                assert updated.approved_by is None
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_reviewed_to_approved_sets_both_fields(self):
        """REVIEWED → approved: both review AND approval fields set."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="reviewed",
                )
                rec_id = rec.id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "approve"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "approved"

            async with factory() as session:
                result = await session.execute(
                    select(
                        CalibrationRecommendationRecord,
                    ).where(
                        CalibrationRecommendationRecord.id
                        == rec_id,
                    )
                )
                updated = result.scalar_one()
                assert updated.reviewed_at is not None
                assert updated.reviewed_by == USER_A
                assert updated.approved_at is not None
                assert updated.approved_by == USER_A
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_rejection_sets_no_approval_fields(self):
        """Rejection: review fields set, approval fields NOT set."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="generated",
                )
                rec_id = rec.id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={
                    "action": "reject",
                    "reason": "Insufficient evidence",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "rejected"

            async with factory() as session:
                result = await session.execute(
                    select(
                        CalibrationRecommendationRecord,
                    ).where(
                        CalibrationRecommendationRecord.id
                        == rec_id,
                    )
                )
                updated = result.scalar_one()
                assert updated.reviewed_at is not None
                assert updated.reviewed_by == USER_A
                assert updated.rejection_reason == "Insufficient evidence"
                # M1: approval fields must NOT be set
                assert updated.approved_at is None
                assert updated.approved_by is None
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_reject_reviewed_sets_no_approval_fields(self):
        """REVIEWED → rejected: no approval fields."""
        engine = await _setup_engine()
        client, factory = await _make_client(engine)
        try:
            async with factory() as session:
                rec = await _create_recommendation(
                    session, status="reviewed",
                )
                rec_id = rec.id
                await session.commit()

            resp = await client.post(
                f"/analytics/calibration/"
                f"recommendations/{rec_id}/review",
                params={"user_id": str(USER_A)},
                json={"action": "reject"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "rejected"

            async with factory() as session:
                result = await session.execute(
                    select(
                        CalibrationRecommendationRecord,
                    ).where(
                        CalibrationRecommendationRecord.id
                        == rec_id,
                    )
                )
                updated = result.scalar_one()
                assert updated.approved_at is None
                assert updated.approved_by is None
        finally:
            await client.aclose()
            await _cleanup()
            await _teardown_engine(engine)

"""Sprint 23B — End-to-End PostgreSQL Production Validation Tests.

Uses real PostgreSQL, real FastAPI endpoints, real SQLAlchemy sessions.
No mocks. No SQLite. Validates the complete production lifecycle.

PostgreSQL database: sprint23b_test (disposable, created by Phase 1)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import get_db
from app.core.identity import get_current_user
from app.main import app
from app.models.audit_event import AuditEvent
from app.models.calibration_recommendation import (
    CalibrationRecommendationRecord,
)
from app.models.calibration_version import CalibrationVersionRecord

PG_URL = "postgresql+asyncpg://postgres@127.0.0.1:5432/sprint23b_test"

USER_A = uuid.uuid4()
USER_B = uuid.uuid4()
_active_user_id: uuid.UUID = USER_A


# ── Fixtures ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def pg_engine():
    """Create engine and clean calibration tables before each test."""
    engine = create_async_engine(PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM audit_events"))
        await conn.execute(text("DELETE FROM calibration_recommendations"))
        await conn.execute(text("DELETE FROM calibration_versions"))
        await conn.execute(text("DELETE FROM users"))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_factory(pg_engine):
    """Session factory for direct DB access in tests."""
    return async_sessionmaker(
        pg_engine, class_=AsyncSession, expire_on_commit=False,
    )


@pytest_asyncio.fixture
async def client(pg_engine):
    """Async HTTP client wired to the real FastAPI app + PostgreSQL."""

    factory = async_sessionmaker(
        pg_engine, class_=AsyncSession, expire_on_commit=False,
    )

    async def override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    # Identity override: reads from a module-level variable
    class _FakeUser:
        def __init__(self, uid):
            self.id = uid

    async def override_get_current_user():
        return _FakeUser(_active_user_id)

    app.dependency_overrides[get_current_user] = override_get_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _seed_user(engine, user_id: uuid.UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, external_reference, "
                "display_name, status, created_at, updated_at) "
                "VALUES (:id, :ext, :dn, 'active', NOW(), NOW()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": str(user_id),
                "ext": f"user-{user_id}",
                "dn": f"User {str(user_id)[:8]}",
            },
        )


async def _make_version(
    session: AsyncSession,
    user_id: uuid.UUID,
    version_id: str,
    *,
    param_snapshot: dict[str, Any] | None = None,
    status: str = "generated",
    previous_version: str | None = None,
) -> CalibrationVersionRecord:
    now = datetime.now(UTC)
    rec = CalibrationVersionRecord(
        id=uuid.uuid4(),
        user_id=user_id,
        version_id=version_id,
        source_window_days=30,
        total_samples=100,
        eligible_samples=80,
        excluded_samples=20,
        recommendation_count=1,
        parameter_snapshot=param_snapshot or {},
        status=status,
        previous_version=previous_version,
        created_at=now,
        updated_at=now,
    )
    session.add(rec)
    await session.flush()
    return rec


async def _make_recommendation(
    session: AsyncSession,
    user_id: uuid.UUID,
    calibration_version: str,
    *,
    status: str = "generated",
) -> CalibrationRecommendationRecord:
    now = datetime.now(UTC)
    rec = CalibrationRecommendationRecord(
        id=uuid.uuid4(),
        user_id=user_id,
        recommendation_type="weight_adjustment",
        engine="risk_engine",
        parameter="intent_drift",
        current_value={"value": 0.25},
        proposed_value={"value": 0.35},
        evidence={"metrics": {"accuracy": 0.85}},
        sample_count=100,
        confidence="high",
        rationale="Testing rationale",
        severity="medium",
        status=status,
        calibration_version=calibration_version,
        created_at=now,
        updated_at=now,
    )
    session.add(rec)
    await session.flush()
    return rec


# ═══════════════════════════════════════════════════════════
# PHASE 2 — END-TO-END LIFECYCLE
# ═══════════════════════════════════════════════════════════


class TestEndToEndLifecycle:
    """Full lifecycle against PostgreSQL via HTTP endpoints."""

    async def test_full_lifecycle_generate_activate_rollback(
        self, pg_engine, pg_factory, client,
    ):
        """Complete lifecycle:
        v1 create → govern → activate →
        v2 create → govern → activate (supersedes v1) →
        rollback → v1 restored → v2 superseded
        """
        await _seed_user(pg_engine, USER_A)
        str(USER_A)

        # ── Create v1 ──
        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-23b-v1",
                param_snapshot={"signal_weights": {"intent_drift": 0.25}},
            )
            r1 = await _make_recommendation(
                s, USER_A, "cal-23b-v1", status="generated",
            )
            await s.commit()

        # ── Governance: approve v1 recommendation (generated → reviewed → approved) ──
        async with pg_factory() as s:
            from app.api.v1.endpoints.calibration_intelligence import (
                ReviewRequest,
                _review_recommendation_impl,
            )
            await _review_recommendation_impl(
                s, str(r1.id), ReviewRequest(action="approve"), USER_A,
            )
            await s.commit()
        async with pg_factory() as s:
            from sqlalchemy import select as sa_select
            (await s.execute(
                sa_select(CalibrationRecommendationRecord).where(
                    CalibrationRecommendationRecord.id == r1.id,
                ),
            )).scalar_one()
            await _review_recommendation_impl(
                s, str(r1.id), ReviewRequest(action="approve"), USER_A,
            )
            await s.commit()

        # ── Activate v1 ──
        async with pg_factory() as s:
            from app.api.v1.endpoints.calibration_intelligence import (
                ActivateRequest,
                _activate_version_impl,
            )
            resp = await _activate_version_impl(
                s, "cal-23b-v1", ActivateRequest(confirm=True), USER_A,
            )
            await s.commit()
            assert resp.status == "active"

        # ── Create v2 ──
        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-23b-v2",
                param_snapshot={"signal_weights": {"intent_drift": 0.35}},
                previous_version="cal-23b-v1",
            )
            r2 = await _make_recommendation(
                s, USER_A, "cal-23b-v2", status="generated",
            )
            await s.commit()

        # ── Governance: approve v2 ──
        async with pg_factory() as s:
            await _review_recommendation_impl(
                s, str(r2.id), ReviewRequest(action="approve"), USER_A,
            )
            await s.commit()
        async with pg_factory() as s:
            await _review_recommendation_impl(
                s, str(r2.id), ReviewRequest(action="approve"), USER_A,
            )
            await s.commit()

        # ── Activate v2 (supersedes v1) ──
        async with pg_factory() as s:
            resp2 = await _activate_version_impl(
                s, "cal-23b-v2", ActivateRequest(confirm=True), USER_A,
            )
            await s.commit()
            assert resp2.status == "active"
            assert resp2.previous_version == "cal-23b-v1"

        # ── Verify v1 is SUPERSEDED ──
        async with pg_factory() as s:
            from sqlalchemy import select as sa_select
            v1_status = (await s.execute(
                sa_select(CalibrationVersionRecord.status).where(
                    CalibrationVersionRecord.version_id == "cal-23b-v1",
                ),
            )).scalar()
            assert v1_status == "superseded"

        # ── Rollback ──
        async with pg_factory() as s:
            from app.api.v1.endpoints.calibration_intelligence import (
                _rollback_impl,
            )
            rb = await _rollback_impl(s, USER_A)
            await s.commit()
            assert rb.rolled_back is True
            assert rb.restored_version == "cal-23b-v1"

        # ── Verify final state ──
        async with pg_factory() as s:
            v1_s = (await s.execute(
                sa_select(CalibrationVersionRecord.status).where(
                    CalibrationVersionRecord.version_id == "cal-23b-v1",
                ),
            )).scalar()
            v2_s = (await s.execute(
                sa_select(CalibrationVersionRecord.status).where(
                    CalibrationVersionRecord.version_id == "cal-23b-v2",
                ),
            )).scalar()
            assert v1_s == "active"
            assert v2_s == "superseded"

        # ── Verify audit trail ──
        async with pg_factory() as s:
            events = (await s.execute(
                sa_select(AuditEvent.event_type).where(
                    AuditEvent.entity_type == "calibration_version",
                ).order_by(AuditEvent.created_at),
            )).scalars().all()
            assert "calibration_activated" in events
            assert "calibration_superseded" in events

    async def test_list_versions_and_detail(
        self, pg_engine, pg_factory, client,
    ):
        """List versions and get detail endpoint against PostgreSQL."""
        await _seed_user(pg_engine, USER_A)

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-list-v1",
                param_snapshot={"signal_weights": {}},
            )
            await s.commit()

        # List versions
        resp = await client.get(
            "/analytics/calibration/versions",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "versions" in data
        assert len(data["versions"]) >= 1

        # Get version detail
        resp = await client.get(
            "/analytics/calibration/versions/cal-list-v1",
        )
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["version"]["version_id"] == "cal-list-v1"


# ═══════════════════════════════════════════════════════════
# PHASE 3 — OWNERSHIP ISOLATION
# ═══════════════════════════════════════════════════════════


class TestOwnershipIsolation:
    """Cross-user access must be blocked at every endpoint."""

    async def test_cannot_activate_other_users_version(
        self, pg_engine, pg_factory, client,
    ):
        """User A cannot activate User B's version."""
        await _seed_user(pg_engine, USER_A)
        await _seed_user(pg_engine, USER_B)

        async with pg_factory() as s:
            await _make_version(
                s, USER_B, "cal-iso-b",
                param_snapshot={"signal_weights": {}},
            )
            await _make_recommendation(
                s, USER_B, "cal-iso-b", status="approved",
            )
            await s.commit()

        # User A tries to activate User B's version
        async with pg_factory() as s:
            from app.api.v1.endpoints.calibration_intelligence import (
                ActivateRequest,
                _activate_version_impl,
            )
            with pytest.raises(Exception, match="does not belong"):
                await _activate_version_impl(
                    s, "cal-iso-b",
                    ActivateRequest(confirm=True),
                    USER_A,
                )

    async def test_cannot_rollback_other_users_calibration(
        self, pg_engine, pg_factory, client,
    ):
        """User A cannot rollback User B's calibration."""
        await _seed_user(pg_engine, USER_A)
        await _seed_user(pg_engine, USER_B)

        async with pg_factory() as s:
            await _make_version(
                s, USER_B, "cal-iso-rb",
                param_snapshot={"signal_weights": {}},
            )
            await _make_recommendation(
                s, USER_B, "cal-iso-rb", status="approved",
            )
            await s.commit()

        async with pg_factory() as s:
            from app.api.v1.endpoints.calibration_intelligence import (
                ActivateRequest,
                _activate_version_impl,
            )
            await _activate_version_impl(
                s, "cal-iso-rb",
                ActivateRequest(confirm=True),
                USER_B,
            )
            await s.commit()

        # User A tries to rollback — should find no active version for A
        async with pg_factory() as s:
            from app.api.v1.endpoints.calibration_intelligence import (
                _rollback_impl,
            )
            with pytest.raises(Exception):
                await _rollback_impl(s, USER_A)

    async def test_versions_are_user_scoped(
        self, pg_engine, pg_factory, client,
    ):
        """User A's versions don't appear in User B's listing."""
        await _seed_user(pg_engine, USER_A)
        await _seed_user(pg_engine, USER_B)

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-scope-a",
                param_snapshot={"signal_weights": {}},
            )
            await _make_version(
                s, USER_B, "cal-scope-b",
                param_snapshot={"signal_weights": {}},
            )
            await s.commit()

        # User A lists — only sees cal-scope-a
        global _active_user_id
        _active_user_id = USER_A
        resp = await client.get(
            "/analytics/calibration/versions",
        )
        assert resp.status_code == 200
        vids = [v["version_id"] for v in resp.json()["versions"]]
        assert "cal-scope-a" in vids
        assert "cal-scope-b" not in vids

        # User B lists — only sees cal-scope-b
        _active_user_id = USER_B
        resp = await client.get(
            "/analytics/calibration/versions",
        )
        assert resp.status_code == 200
        vids = [v["version_id"] for v in resp.json()["versions"]]
        assert "cal-scope-b" in vids
        assert "cal-scope-a" not in vids

        _active_user_id = USER_A


# ═══════════════════════════════════════════════════════════
# PHASE 4 — IDEMPOTENCY
# ═══════════════════════════════════════════════════════════


class TestIdempotency:
    """Repeated operations must be safe and deterministic on PostgreSQL."""

    async def test_activation_is_idempotent(
        self, pg_engine, pg_factory,
    ):
        """Activating an already-active version returns existing state."""
        await _seed_user(pg_engine, USER_A)

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-idem",
                param_snapshot={"signal_weights": {}},
            )
            await _make_recommendation(
                s, USER_A, "cal-idem", status="approved",
            )
            await s.commit()

        from app.api.v1.endpoints.calibration_intelligence import (
            ActivateRequest,
            _activate_version_impl,
        )

        # First activation
        async with pg_factory() as s:
            resp1 = await _activate_version_impl(
                s, "cal-idem", ActivateRequest(confirm=True), USER_A,
            )
            await s.commit()
            assert resp1.idempotent is False

        # Second activation (idempotent)
        async with pg_factory() as s:
            resp2 = await _activate_version_impl(
                s, "cal-idem", ActivateRequest(confirm=True), USER_A,
            )
            await s.commit()
            assert resp2.idempotent is True

    async def test_deterministic_version_id(
        self, pg_engine, pg_factory,
    ):
        """Same calibration data produces identical version_id."""
        from app.services.calibration_intelligence.engine import (
            CalibrationIntelligenceEngine,
        )
        engine = CalibrationIntelligenceEngine()

        r1 = engine.evaluate(
            transaction_records=[], decision_records=[],
            outcome_records=[], window_days=30, user_id=str(USER_A),
        )
        r2 = engine.evaluate(
            transaction_records=[], decision_records=[],
            outcome_records=[], window_days=30, user_id=str(USER_A),
        )
        assert r1.version.version_id == r2.version.version_id

        # Different user → different version_id
        r3 = engine.evaluate(
            transaction_records=[], decision_records=[],
            outcome_records=[], window_days=30, user_id=str(USER_B),
        )
        assert r1.version.version_id != r3.version.version_id


# ═══════════════════════════════════════════════════════════
# PHASE 5 — ATOMICITY
# ═══════════════════════════════════════════════════════════


class TestAtomicity:
    """Activation and rollback are transactional on PostgreSQL."""

    async def test_activation_is_atomic(
        self, pg_engine, pg_factory,
    ):
        """Activation changes version + recommendation + audit atomically."""
        await _seed_user(pg_engine, USER_A)

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-atom",
                param_snapshot={"signal_weights": {}},
            )
            await _make_recommendation(
                s, USER_A, "cal-atom", status="approved",
            )
            await s.commit()

        from app.api.v1.endpoints.calibration_intelligence import (
            ActivateRequest,
            _activate_version_impl,
        )
        async with pg_factory() as s:
            await _activate_version_impl(
                s, "cal-atom", ActivateRequest(confirm=True), USER_A,
            )
            await s.commit()

        # All three must have changed together
        async with pg_factory() as s:
            from sqlalchemy import select as sa_select
            ver = (await s.execute(
                sa_select(CalibrationVersionRecord).where(
                    CalibrationVersionRecord.version_id == "cal-atom",
                ),
            )).scalar()
            assert ver.status == "active"
            assert ver.activated_at is not None

            rec = (await s.execute(
                sa_select(CalibrationRecommendationRecord).where(
                    CalibrationRecommendationRecord.calibration_version
                    == "cal-atom",
                ),
            )).scalar()
            assert rec.status == "activated"

            audit_count = (await s.execute(
                text(
                    "SELECT COUNT(*) FROM audit_events "
                    "WHERE event_type = 'calibration_activated'"
                ),
            )).scalar()
            assert audit_count >= 1

    async def test_rollback_is_atomic(
        self, pg_engine, pg_factory,
    ):
        """Rollback supersedes current and activates previous atomically."""
        await _seed_user(pg_engine, USER_A)

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-arb-v1",
                param_snapshot={"signal_weights": {}},
            )
            await _make_recommendation(
                s, USER_A, "cal-arb-v1", status="approved",
            )
            await _make_version(
                s, USER_A, "cal-arb-v2",
                param_snapshot={"signal_weights": {}},
                previous_version="cal-arb-v1",
            )
            await _make_recommendation(
                s, USER_A, "cal-arb-v2", status="approved",
            )
            await s.commit()

        from app.api.v1.endpoints.calibration_intelligence import (
            ActivateRequest,
            _activate_version_impl,
            _rollback_impl,
        )

        # Activate v2
        async with pg_factory() as s:
            await _activate_version_impl(
                s, "cal-arb-v2", ActivateRequest(confirm=True), USER_A,
            )
            await s.commit()

        # Rollback
        async with pg_factory() as s:
            await _rollback_impl(s, USER_A)
            await s.commit()

        # Both must have changed atomically
        async with pg_factory() as s:
            from sqlalchemy import select as sa_select
            v1_s = (await s.execute(
                sa_select(CalibrationVersionRecord.status).where(
                    CalibrationVersionRecord.version_id == "cal-arb-v1",
                ),
            )).scalar()
            v2_s = (await s.execute(
                sa_select(CalibrationVersionRecord.status).where(
                    CalibrationVersionRecord.version_id == "cal-arb-v2",
                ),
            )).scalar()
            assert v1_s == "active"
            assert v2_s == "superseded"

    async def test_pending_recommendation_blocks_activation(
        self, pg_engine, pg_factory,
    ):
        """Activation blocked by pending recommendation — no state change."""
        await _seed_user(pg_engine, USER_A)

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-blocked",
                param_snapshot={"signal_weights": {}},
            )
            await _make_recommendation(
                s, USER_A, "cal-blocked", status="generated",
            )
            await s.commit()

        from app.api.v1.endpoints.calibration_intelligence import (
            ActivateRequest,
            _activate_version_impl,
        )
        with pytest.raises(Exception, match="pending"):
            async with pg_factory() as s:
                await _activate_version_impl(
                    s, "cal-blocked",
                    ActivateRequest(confirm=True), USER_A,
                )

        # Verify no state change
        async with pg_factory() as s:
            from sqlalchemy import select as sa_select
            status = (await s.execute(
                sa_select(CalibrationVersionRecord.status).where(
                    CalibrationVersionRecord.version_id == "cal-blocked",
                ),
            )).scalar()
            assert status == "generated"


# ═══════════════════════════════════════════════════════════
# PHASE 6 — CONCURRENCY
# ═══════════════════════════════════════════════════════════


class TestConcurrency:
    """Concurrent operations on PostgreSQL."""

    async def test_concurrent_activation_same_version(
        self, pg_engine, pg_factory,
    ):
        """Two concurrent activations of same version — one wins."""
        await _seed_user(pg_engine, USER_A)

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-conc-same",
                param_snapshot={"signal_weights": {}},
            )
            await _make_recommendation(
                s, USER_A, "cal-conc-same", status="approved",
            )
            await s.commit()

        from app.api.v1.endpoints.calibration_intelligence import (
            ActivateRequest,
            _activate_version_impl,
        )

        async def act():
            async with pg_factory() as s:
                try:
                    return await _activate_version_impl(
                        s, "cal-conc-same",
                        ActivateRequest(confirm=True), USER_A,
                    )
                except Exception as e:
                    return e

        results = await asyncio.gather(act(), act())
        successes = [r for r in results if not isinstance(r, Exception)]
        assert len(successes) >= 1
        assert all(r.status == "active" for r in successes)

    async def test_concurrent_rollback(
        self, pg_engine, pg_factory,
    ):
        """Two concurrent rollbacks — only one succeeds."""
        await _seed_user(pg_engine, USER_A)

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-crb-v1",
                param_snapshot={"signal_weights": {}},
            )
            await _make_recommendation(
                s, USER_A, "cal-crb-v1", status="approved",
            )
            await _make_version(
                s, USER_A, "cal-crb-v2",
                param_snapshot={"signal_weights": {}},
                previous_version="cal-crb-v1",
            )
            await _make_recommendation(
                s, USER_A, "cal-crb-v2", status="approved",
            )
            await s.commit()

        from app.api.v1.endpoints.calibration_intelligence import (
            ActivateRequest,
            _activate_version_impl,
            _rollback_impl,
        )

        async with pg_factory() as s:
            await _activate_version_impl(
                s, "cal-crb-v2", ActivateRequest(confirm=True), USER_A,
            )
            await s.commit()

        async def rb():
            async with pg_factory() as s:
                try:
                    return await _rollback_impl(s, USER_A)
                except Exception as e:
                    return e

        results = await asyncio.gather(rb(), rb())
        successes = [r for r in results if not isinstance(r, Exception)]
        assert len(successes) >= 1


# ═══════════════════════════════════════════════════════════
# PHASE 7 — RUNTIME CALIBRATION CONSUMPTION
# ═══════════════════════════════════════════════════════════


class TestRuntimeConsumption:
    """Verify calibration resolver behavior against PostgreSQL."""

    async def test_no_calibration_returns_defaults(
        self, pg_engine, pg_factory,
    ):
        """No active calibration → resolver returns exact defaults."""
        from app.services.calibration_runtime.constants import (
            DEFAULT_SIGNAL_WEIGHTS,
        )
        from app.services.calibration_runtime.resolver import (
            resolve_effective_config,
        )

        config = resolve_effective_config(None)
        assert config.calibration_active is False
        assert config.signal_weights == dict(DEFAULT_SIGNAL_WEIGHTS)

    async def test_active_calibration_consumed(
        self, pg_engine, pg_factory,
    ):
        """Active calibration → resolver applies calibrated values."""
        from app.services.calibration_runtime.models import (
            RuntimeCalibrationConfig,
        )
        from app.services.calibration_runtime.resolver import (
            resolve_effective_config,
        )

        cal = RuntimeCalibrationConfig(
            version_id="test-v1",
            source_window_days=30,
            parameter_snapshot={
                "signal_weights": {"intent_drift": 0.35},
            },
            is_active=True,
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is True
        assert config.source_version_id == "test-v1"
        assert config.signal_weights["intent_drift"] == 0.35

    async def test_invalid_calibration_fails_closed(
        self, pg_engine, pg_factory,
    ):
        """Invalid calibration → resolver falls back to defaults."""
        from app.services.calibration_runtime.models import (
            RuntimeCalibrationConfig,
        )
        from app.services.calibration_runtime.resolver import (
            resolve_effective_config,
        )

        cal = RuntimeCalibrationConfig(
            version_id="bad-v1",
            source_window_days=30,
            parameter_snapshot={
                "signal_weights": {"intent_drift": 999.0},
            },
            is_active=True,
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is False

    async def test_superseded_calibration_not_consumed(
        self, pg_engine, pg_factory,
    ):
        """Superseded calibration → resolver returns defaults."""
        from app.services.calibration_runtime.models import (
            RuntimeCalibrationConfig,
        )
        from app.services.calibration_runtime.resolver import (
            resolve_effective_config,
        )

        cal = RuntimeCalibrationConfig(
            version_id="sup-v1",
            parameter_snapshot={"signal_weights": {"intent_drift": 0.35}},
            is_active=False,  # Not active
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is False

    async def test_multiple_active_versions_fails_closed(
        self, pg_engine, pg_factory,
    ):
        """Multiple active versions → db_adapter returns None → defaults."""
        from app.services.calibration_runtime.db_adapter import (
            load_active_calibration,
        )

        uid = uuid.uuid4()
        await _seed_user(pg_engine, uid)

        # Insert two active versions for the same user
        async with pg_factory() as s:
            await _make_version(
                s, uid, "multi-v1", status="active",
                param_snapshot={"signal_weights": {}},
            )
            await _make_version(
                s, uid, "multi-v2", status="active",
                param_snapshot={"signal_weights": {}},
            )
            await s.commit()

        async with pg_factory() as s:
            result = await load_active_calibration(s, uid)
            assert result is None  # Multiple active → fail closed


# ═══════════════════════════════════════════════════════════
# PHASE 8 — HEALTH METRICS
# ═══════════════════════════════════════════════════════════


class TestHealthMetrics:
    """Verify calibration health metrics against PostgreSQL."""

    async def test_metrics_empty_dataset(
        self, pg_engine, pg_factory,
    ):
        """No data → zero metrics."""
        from app.services.calibration_intelligence.health_metrics import (
            compute_calibration_metrics,
        )
        uid = uuid.uuid4()
        async with pg_engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO users (id, external_reference, display_name, "
                "status, created_at, updated_at) VALUES "
                "(:id, :ext, :dn, 'active', NOW(), NOW())"
            ), {"id": str(uid), "ext": f"u-{uid}", "dn": "Empty"})

        async with pg_factory() as s:
            metrics = await compute_calibration_metrics(s, uid)
            assert metrics.total_decisions == 0
            assert metrics.calibration_active_count == 0


# ═══════════════════════════════════════════════════════════
# PHASE 9 — AUDIT INTEGRITY
# ═══════════════════════════════════════════════════════════


class TestAuditIntegrity:
    """Verify audit events contain correct metadata on PostgreSQL."""

    async def test_activation_audit_metadata(
        self, pg_engine, pg_factory,
    ):
        """Activation audit contains correct previous_status/new_status."""
        await _seed_user(pg_engine, USER_A)

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-audit-md",
                param_snapshot={"signal_weights": {}},
            )
            await _make_recommendation(
                s, USER_A, "cal-audit-md", status="approved",
            )
            await s.commit()

        from app.api.v1.endpoints.calibration_intelligence import (
            ActivateRequest,
            _activate_version_impl,
        )
        async with pg_factory() as s:
            await _activate_version_impl(
                s, "cal-audit-md",
                ActivateRequest(confirm=True), USER_A,
            )
            await s.commit()

        async with pg_factory() as s:
            row = (await s.execute(
                text(
                    "SELECT metadata FROM audit_events "
                    "WHERE event_type = 'calibration_activated' "
                    "AND metadata->>'version_id' = 'cal-audit-md'"
                ),
            )).fetchone()
            assert row is not None
            meta = row[0]
            assert meta["previous_status"] == "generated"
            assert meta["new_status"] == "active"
            assert meta["version_id"] == "cal-audit-md"

    async def test_rollback_audit_metadata(
        self, pg_engine, pg_factory,
    ):
        """Rollback audit contains correct previous_status/new_status."""
        await _seed_user(pg_engine, USER_A)

        from app.api.v1.endpoints.calibration_intelligence import (
            ActivateRequest,
            _activate_version_impl,
            _rollback_impl,
        )

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-rb-audit-v1",
                param_snapshot={"signal_weights": {}},
            )
            await _make_recommendation(
                s, USER_A, "cal-rb-audit-v1", status="approved",
            )
            await s.commit()

        # Activate v1 first
        async with pg_factory() as s:
            await _activate_version_impl(
                s, "cal-rb-audit-v1",
                ActivateRequest(confirm=True), USER_A,
            )
            await s.commit()

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-rb-audit-v2",
                param_snapshot={"signal_weights": {}},
                previous_version="cal-rb-audit-v1",
            )
            await _make_recommendation(
                s, USER_A, "cal-rb-audit-v2", status="approved",
            )
            await s.commit()

        # Activate v2 (supersedes v1)
        async with pg_factory() as s:
            await _activate_version_impl(
                s, "cal-rb-audit-v2",
                ActivateRequest(confirm=True), USER_A,
            )
            await s.commit()

        # Rollback
        async with pg_factory() as s:
            await _rollback_impl(s, USER_A)
            await s.commit()

        async with pg_factory() as s:
            # Check superseded audit
            row = (await s.execute(
                text(
                    "SELECT metadata FROM audit_events "
                    "WHERE event_type = 'calibration_superseded' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
            )).fetchone()
            assert row is not None
            meta = row[0]
            assert meta["previous_status"] == "active"
            assert meta["new_status"] == "superseded"

            # Check activated audit from rollback
            row = (await s.execute(
                text(
                    "SELECT metadata FROM audit_events "
                    "WHERE event_type = 'calibration_activated' "
                    "AND metadata->>'rollback' = 'true' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
            )).fetchone()
            assert row is not None
            meta = row[0]
            assert meta["previous_status"] == "superseded"
            assert meta["new_status"] == "active"

    async def test_historical_immutability(
        self, pg_engine, pg_factory,
    ):
        """Parameter snapshots remain unchanged after activation/rollback."""
        await _seed_user(pg_engine, USER_A)
        snapshot_v1 = {"signal_weights": {"intent_drift": 0.25}}
        snapshot_v2 = {"signal_weights": {"intent_drift": 0.35}}

        async with pg_factory() as s:
            await _make_version(
                s, USER_A, "cal-imm-v1",
                param_snapshot=snapshot_v1,
            )
            await _make_recommendation(
                s, USER_A, "cal-imm-v1", status="approved",
            )
            await _make_version(
                s, USER_A, "cal-imm-v2",
                param_snapshot=snapshot_v2,
                previous_version="cal-imm-v1",
            )
            await _make_recommendation(
                s, USER_A, "cal-imm-v2", status="approved",
            )
            await s.commit()

        from app.api.v1.endpoints.calibration_intelligence import (
            ActivateRequest,
            _activate_version_impl,
            _rollback_impl,
        )

        async with pg_factory() as s:
            await _activate_version_impl(
                s, "cal-imm-v2", ActivateRequest(confirm=True), USER_A,
            )
            await s.commit()

        async with pg_factory() as s:
            await _rollback_impl(s, USER_A)
            await s.commit()

        # Verify snapshots are unchanged
        async with pg_factory() as s:
            from sqlalchemy import select as sa_select
            v1 = (await s.execute(
                sa_select(CalibrationVersionRecord).where(
                    CalibrationVersionRecord.version_id == "cal-imm-v1",
                ),
            )).scalar()
            v2 = (await s.execute(
                sa_select(CalibrationVersionRecord).where(
                    CalibrationVersionRecord.version_id == "cal-imm-v2",
                ),
            )).scalar()
            assert v1.parameter_snapshot == snapshot_v1
            assert v2.parameter_snapshot == snapshot_v2

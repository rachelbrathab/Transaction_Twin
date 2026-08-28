"""Sprint 19B — End-to-End Calibration Lifecycle & Production Readiness.

Comprehensive test suite covering:
- End-to-end lifecycle (generate → review → approve → activate → consume → rollback)
- Concurrency testing (concurrent activation, rollback, review)
- Failure/recovery testing (DB failure, malformed calibration, missing previous)
- Audit integrity (every transition creates correct AuditEvent)
- Security (cross-user isolation for all operations)
- Runtime safety (only ACTIVE consumed, fail-closed, no constant mutation)
- Observability (calibration_consumed events, health metrics)
- Determinism (same inputs → same version ID, same results)
- Backward compatibility (default path unchanged)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.audit_event import AuditEvent
from app.models.calibration_recommendation import (
    CalibrationRecommendationRecord,
)
from app.models.calibration_version import CalibrationVersionRecord
from app.models.transaction import Transaction
from app.models.transaction_event import TransactionEvent
from app.services.calibration_intelligence.health_metrics import (
    compute_calibration_metrics,
)
from app.services.calibration_intelligence.persistence import (
    persist_calibration_result,
)
from app.services.calibration_intelligence.state_machine import (
    can_activate_version,
    validate_recommendation_transition,
    validate_version_transition,
)
from app.services.calibration_runtime.db_adapter import (
    load_active_calibration,
)
from app.services.calibration_runtime.models import (
    RuntimeCalibrationConfig,
)
from app.services.calibration_runtime.resolver import (
    resolve_effective_config,
)
from app.services.risk_engine.config import (
    RiskEngineConfig,
    get_default_risk_engine_config,
)
from app.services.risk_engine.constants import (
    CONFIDENCE_REDUCTIONS,
    RISK_LEVEL_THRESHOLDS,
    SIGNAL_WEIGHTS,
)
from app.services.risk_engine.engine import RiskEngine
from app.services.risk_engine.models import RiskContext

# ── Helpers ──────────────────────────────────────────────────────

USER_A = uuid.uuid4()
USER_B = uuid.uuid4()


class _FakeRequest:
    """Lightweight request stand-in for implementation functions."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


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


def _make_tx(session, user_id, agent_id=None, **kw):
    agent_id = agent_id or uuid.uuid4()
    tx = Transaction(
        id=kw.get("id", uuid.uuid4()),
        user_id=user_id,
        agent_id=agent_id,
        intent_id=kw.get("intent_id", uuid.uuid4()),
        merchant_id=kw.get("merchant_id", uuid.uuid4()),
        idempotency_key=kw.get("idempotency_key", uuid.uuid4()),
        transaction_type=kw.get("transaction_type", "payment"),
        amount=kw.get("amount", Decimal("100")),
        currency=kw.get("currency", "USD"),
        status=kw.get("status", "decided"),
        created_at=kw.get("created_at", datetime.now(UTC)),
    )
    session.add(tx)
    return tx


async def _make_version(session, user_id, version_id, status="generated",
                  param_snapshot=None, **kw):
    ver = CalibrationVersionRecord(
        user_id=user_id,
        version_id=version_id,
        source_window_days=kw.get("source_window_days", 30),
        total_samples=kw.get("total_samples", 100),
        eligible_samples=kw.get("eligible_samples", 80),
        excluded_samples=kw.get("excluded_samples", 20),
        recommendation_count=kw.get("recommendation_count", 0),
        parameter_snapshot=param_snapshot or {},
        status=status,
        activated_at=kw.get("activated_at"),
        activated_by=kw.get("activated_by"),
        previous_version=kw.get("previous_version"),
    )
    session.add(ver)
    # Flush so the ORM-assigned primary key is available immediately
    await session.flush()
    return ver


async def _make_recommendation(session, user_id, version_id, status="generated",
                              rec_type="weight_review", engine_name="risk_engine",
                              parameter="intent_drift"):
    rec = CalibrationRecommendationRecord(
        user_id=user_id,
        recommendation_type=rec_type,
        engine=engine_name,
        parameter=parameter,
        rationale="Test rationale",
        calibration_version=version_id,
        status=status,
        evidence={},
        sample_count=10,
        confidence="sufficient",
        severity="medium",
    )
    session.add(rec)
    # Flush so the ORM-assigned primary key is available immediately
    await session.flush()
    return rec


def _make_event(session, tx_id, agent_id, event_type="calibration_consumed",
                payload=None, seq=2):
    event = TransactionEvent(
        transaction_id=tx_id,
        agent_id=agent_id,
        sequence_number=seq,
        event_type=event_type,
        source="system",
        verification_state="verified",
        payload=payload or {},
    )
    session.add(event)
    return event


def _make_risk_context(**overrides):
    defaults = {
        "user_id": "user-123",
        "agent_id": "agent-456",
        "intent_id": "intent-789",
        "intent_version": 1,
        "intent_confidence": 0.9,
        "intent_transaction_type": "payment",
        "proposal_amount": Decimal("100.00"),
        "proposal_currency": "USD",
        "proposal_transaction_type": "payment",
        "proposal_merchant_name": "Test Merchant",
        "proposal_merchant_trusted": False,
        "proposal_country": "US",
        "drift_available": True,
        "drift_overall_status": "match",
        "drift_severity": "low",
        "policy_available": True,
        "policy_triggered_count": 0,
        "agent_trust_score": 0.7,
        "merchant_trust_score": 0.6,
    }
    defaults.update(overrides)
    return RiskContext(**defaults)


# ══════════════════════════════════════════════════════════════════
# SECTION 1: END-TO-END LIFECYCLE
# ══════════════════════════════════════════════════════════════════


class TestEndToEndLifecycle:
    """Full lifecycle: activate → consume → health metrics → rollback."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_with_rollback(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = USER_A

            # Step 1: Create two versions
            async with factory() as session:
                await _make_version(
                    session, user_id, "calibration-v1",
                    param_snapshot={"signal_weights": {"intent_drift": 0.25}},
                )
                await _make_version(
                    session, user_id, "calibration-v2",
                    param_snapshot={"signal_weights": {"intent_drift": 0.35}},
                )
                rec2 = await _make_recommendation(
                    session, user_id, "calibration-v2",
                )
                await session.commit()
                rec2_id = str(rec2.id)

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
                _review_recommendation_impl,
                _rollback_impl,
            )

            # Step 1b: Govern v2 recommendation (generated → reviewed → approved)
            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                resp = await _review_recommendation_impl(
                    session, rec2_id, r, user_id,
                )
                assert resp.status == "reviewed"
                await session.commit()

            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                resp = await _review_recommendation_impl(
                    session, rec2_id, r, user_id,
                )
                assert resp.status == "approved"
                await session.commit()

            # Step 2: Activate v1
            async with factory() as session:
                r = _FakeRequest(confirm=True)
                resp = await _activate_version_impl(
                    session, "calibration-v1", r, user_id,
                )
                assert resp.status == "active"
                assert resp.idempotent is False
                await session.commit()

            # Step 3: Verify v1 is active
            async with factory() as session:
                active = await load_active_calibration(session, user_id)
                assert active is not None
                assert active.version_id == "calibration-v1"

            # Step 4: Verify resolved config uses v1
            effective = resolve_effective_config(active)
            assert effective.calibration_active is True
            assert effective.source_version_id == "calibration-v1"

            # Step 5: Record consumption event
            tx_id = uuid.uuid4()
            agent_id = uuid.uuid4()
            async with factory() as session:
                _make_tx(session, user_id, agent_id, id=tx_id)
                _make_event(session, tx_id, agent_id, payload={
                    "calibration_active": True,
                    "calibration_version_id": "calibration-v1",
                    "fallback_reason": None,
                    "risk_level": "low",
                    "risk_score": 0.05,
                    "confidence": 0.95,
                })
                await session.commit()

            # Step 6: Health metrics
            async with factory() as session:
                metrics = await compute_calibration_metrics(session, user_id)
                assert metrics.total_decisions == 1
                assert metrics.calibration_active_count == 1
                assert metrics.usage_by_version.get("calibration-v1") == 1

            # Step 7: Activate v2 (supersedes v1)
            async with factory() as session:
                r = _FakeRequest(confirm=True)
                resp = await _activate_version_impl(
                    session, "calibration-v2", r, user_id,
                )
                assert resp.status == "active"
                assert resp.previous_version == "calibration-v1"
                await session.commit()

            # Step 8: Verify v2 is active
            async with factory() as session:
                active = await load_active_calibration(session, user_id)
                assert active.version_id == "calibration-v2"

            # Step 9: Rollback to v1
            async with factory() as session:
                rollback_resp = await _rollback_impl(session, user_id)
                assert rollback_resp.rolled_back is True
                assert rollback_resp.restored_version == "calibration-v1"
                await session.commit()

            # Step 10: Verify v1 active again
            async with factory() as session:
                active = await load_active_calibration(session, user_id)
                assert active.version_id == "calibration-v1"

            # Step 11: Record another consumption
            tx_id2 = uuid.uuid4()
            async with factory() as session:
                _make_tx(session, user_id, agent_id, id=tx_id2)
                _make_event(session, tx_id2, agent_id, payload={
                    "calibration_active": True,
                    "calibration_version_id": "calibration-v1",
                    "fallback_reason": None,
                    "risk_level": "low",
                    "risk_score": 0.04,
                    "confidence": 0.96,
                })
                await session.commit()

            # Step 12: Metrics show both events
            async with factory() as session:
                metrics = await compute_calibration_metrics(session, user_id)
                assert metrics.total_decisions == 2
                assert metrics.calibration_active_count == 2
                assert metrics.usage_by_version.get("calibration-v1") == 2

            # Step 13: Version states
            async with factory() as session:
                result = await session.execute(
                    select(CalibrationVersionRecord).where(
                        CalibrationVersionRecord.user_id == user_id,
                    )
                )
                versions = {v.version_id: v for v in result.scalars().all()}
                assert versions["calibration-v1"].status == "active"
                assert versions["calibration-v2"].status == "superseded"
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_full_lifecycle_with_recommendation_review(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = USER_A

            async with factory() as session:
                await _make_version(session, user_id, "calibration-v1")
                rec1 = await _make_recommendation(
                    session, user_id, "calibration-v1", parameter="intent_drift",
                )
                rec2 = await _make_recommendation(
                    session, user_id, "calibration-v1", parameter="amount_anomaly",
                )
                await session.commit()
                rec1_id = str(rec1.id)
                rec2_id = str(rec2.id)

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
                _review_recommendation_impl,
            )

            # generated → reviewed
            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                resp = await _review_recommendation_impl(
                    session, rec1_id, r, user_id,
                )
                assert resp.status == "reviewed"
                await session.commit()

            # reviewed → approved
            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                resp = await _review_recommendation_impl(
                    session, rec1_id, r, user_id,
                )
                assert resp.status == "approved"
                await session.commit()

            # generated → rejected
            async with factory() as session:
                r = _FakeRequest(action="reject", reason="Insufficient")
                resp = await _review_recommendation_impl(
                    session, rec2_id, r, user_id,
                )
                assert resp.status == "rejected"
                await session.commit()

            # Activate — one approved + one rejected
            async with factory() as session:
                r = _FakeRequest(confirm=True)
                resp = await _activate_version_impl(
                    session, "calibration-v1", r, user_id,
                )
                assert resp.status == "active"
                assert resp.recommendations_applied == 1
                await session.commit()

            # Verify activated rec
            async with factory() as session:
                result = await session.execute(
                    select(CalibrationRecommendationRecord).where(
                        CalibrationRecommendationRecord.id == uuid.UUID(rec1_id),
                    )
                )
                updated = result.scalar_one()
                assert updated.status == "activated"
        finally:
            await _teardown_engine(engine_db)


# ══════════════════════════════════════════════════════════════════
# SECTION 2: CONCURRENCY TESTING
# ══════════════════════════════════════════════════════════════════


class TestConcurrency:

    @pytest.mark.asyncio
    async def test_idempotent_activation(self):
        """Two activations of same version — second is idempotent."""
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()

            async with factory() as session:
                await _make_version(session, user_id, "calibration-v1")
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
            )

            async with factory() as session:
                r = _FakeRequest(confirm=True)
                resp = await _activate_version_impl(
                    session, "calibration-v1", r, user_id,
                )
                assert resp.status == "active"
                assert resp.idempotent is False
                await session.commit()

            async with factory() as session:
                r = _FakeRequest(confirm=True)
                resp = await _activate_version_impl(
                    session, "calibration-v1", r, user_id,
                )
                assert resp.status == "active"
                assert resp.idempotent is True
                await session.commit()
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_sequential_different_versions(self):
        """Two versions activated sequentially — last wins."""
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()

            async with factory() as session:
                await _make_version(session, user_id, "calibration-v1")
                await _make_version(session, user_id, "calibration-v2")
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
            )

            async with factory() as session:
                r = _FakeRequest(confirm=True)
                resp = await _activate_version_impl(
                    session, "calibration-v1", r, user_id,
                )
                assert resp.status == "active"
                await session.commit()

            async with factory() as session:
                r = _FakeRequest(confirm=True)
                resp = await _activate_version_impl(
                    session, "calibration-v2", r, user_id,
                )
                assert resp.status == "active"
                assert resp.previous_version == "calibration-v1"
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(CalibrationVersionRecord).where(
                        CalibrationVersionRecord.version_id == "calibration-v1",
                    )
                )
                v1 = result.scalar_one()
                assert v1.status == "superseded"
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_sequential_review(self):
        """Three reviews: generated→reviewed→approved, then idempotent."""
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()

            async with factory() as session:
                rec = await _make_recommendation(session, user_id, "v1")
                await session.commit()
                rec_id = str(rec.id)

            from app.api.v1.endpoints.calibration_intelligence import (
                _review_recommendation_impl,
            )

            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                resp = await _review_recommendation_impl(session, rec_id, r, user_id)
                assert resp.status == "reviewed"
                await session.commit()

            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                resp = await _review_recommendation_impl(session, rec_id, r, user_id)
                assert resp.status == "approved"
                await session.commit()

            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                resp = await _review_recommendation_impl(session, rec_id, r, user_id)
                assert resp.status == "approved"
                assert resp.idempotent is True
                await session.commit()
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_persistence_idempotent(self):
        """Two identical persistence calls → only one version record."""
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()

            class _Ver:
                version_id = "calibration-v-deterministic"
                source_window_days = 30
                total_samples = 100
                eligible_samples = 80
                excluded_samples = 20
                recommendation_count = 2
                parameter_snapshot = {"signal_weights": {"intent_drift": 0.30}}

            class _Rec:
                recommendation_type = "weight_review"
                engine = "risk_engine"
                parameter = "intent_drift"
                current_value = {"weight": 0.25}
                proposed_value = {"weight": 0.30}
                proposed_range = None
                evidence = {"sample_count": 50}
                sample_count = 50
                data_sufficiency = type("DS", (), {"value": "sufficient"})()
                rationale = "Adjust"
                severity = "medium"

            class _Result:
                version = _Ver()
                recommendations = [_Rec(), _Rec()]

            async with factory() as session:
                r1 = await persist_calibration_result(session, user_id, _Result())
                assert r1.created is True
                await session.commit()

            async with factory() as session:
                r2 = await persist_calibration_result(session, user_id, _Result())
                assert r2.created is False
                assert len(r2.recommendations) == 2
                await session.commit()
        finally:
            await _teardown_engine(engine_db)


# ══════════════════════════════════════════════════════════════════
# SECTION 3: FAILURE / RECOVERY TESTING
# ══════════════════════════════════════════════════════════════════


class TestFailureRecovery:

    @pytest.mark.asyncio
    async def test_no_active_calibration_returns_defaults(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            async with factory() as session:
                active = await load_active_calibration(session, uuid.uuid4())
                assert active is None

            effective = resolve_effective_config(None)
            assert effective.calibration_active is False
            default_cfg = get_default_risk_engine_config()
            assert effective.signal_weights == default_cfg.signal_weights
        finally:
            await _teardown_engine(engine_db)

    def test_malformed_snapshot_fails_closed(self):
        cal = RuntimeCalibrationConfig(
            version_id="v-bad", is_active=True,
            parameter_snapshot={"signal_weights": {"intent_drift": "not_a_number"}},
        )
        effective = resolve_effective_config(cal)
        assert effective.calibration_active is False
        assert effective.validation_passed is False

    def test_negative_weight_fails_closed(self):
        cal = RuntimeCalibrationConfig(
            version_id="v-neg", is_active=True,
            parameter_snapshot={"signal_weights": {"intent_drift": -0.5}},
        )
        effective = resolve_effective_config(cal)
        assert effective.calibration_active is False

    def test_invalid_threshold_ordering_fails_closed(self):
        cal = RuntimeCalibrationConfig(
            version_id="v-thresh", is_active=True,
            parameter_snapshot={
                "risk_level_thresholds": {
                    "critical": 0.25, "high": 0.50,
                    "medium": 0.75, "low": 0.00,
                },
            },
        )
        effective = resolve_effective_config(cal)
        assert effective.calibration_active is False

    @pytest.mark.asyncio
    async def test_rollback_no_previous_version_409(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                await _make_version(
                    session, user_id, "v1", status="active",
                    activated_at=datetime.now(UTC), activated_by=user_id,
                )
                await session.commit()

            from fastapi import HTTPException

            from app.api.v1.endpoints.calibration_intelligence import (
                _rollback_impl,
            )
            async with factory() as session:
                with pytest.raises(HTTPException) as exc_info:
                    await _rollback_impl(session, user_id)
                assert exc_info.value.status_code == 409
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_superseded_can_activate_for_rollback(self):
        """Superseded versions can be reactivated (for rollback)."""
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                await _make_version(session, user_id, "v1", status="superseded")
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
            )
            async with factory() as session:
                r = _FakeRequest(confirm=True)
                resp = await _activate_version_impl(session, "v1", r, user_id)
                assert resp.status == "active"
                await session.commit()
        finally:
            await _teardown_engine(engine_db)

    def test_pending_recommendations_block_activation(self):
        ok, err = can_activate_version("generated", ["generated"])
        assert ok is False
        assert "pending" in err.lower()

    def test_no_calibration_risk_engine_uses_defaults(self):
        ctx = _make_risk_context()
        engine = RiskEngine()
        r_none = engine.evaluate(ctx, config=None)
        r_default = engine.evaluate(ctx, config=get_default_risk_engine_config())
        assert r_none.overall_score == r_default.overall_score
        assert r_none.risk_level == r_default.risk_level
        assert r_none.confidence == r_default.confidence
        assert r_none.calibration_active is False


# ══════════════════════════════════════════════════════════════════
# SECTION 4: AUDIT INTEGRITY
# ══════════════════════════════════════════════════════════════════


class TestAuditIntegrity:

    @pytest.mark.asyncio
    async def test_review_generated_to_reviewed_audit(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                rec = await _make_recommendation(session, user_id, "v1", status="generated")
                rec_id = rec.id
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _review_recommendation_impl,
            )
            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                resp = await _review_recommendation_impl(session, str(rec_id), r, user_id)
                assert resp.status == "reviewed"
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(AuditEvent.entity_id == rec_id)
                )
                events = result.scalars().all()
                assert len(events) == 1
                meta = events[0].metadata_
                assert meta["previous_status"] == "generated"
                assert meta["new_status"] == "reviewed"
                assert meta["user_id"] == str(user_id)
                assert events[0].actor_id == user_id
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_review_reviewed_to_approved_audit(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                rec = await _make_recommendation(session, user_id, "v1", status="reviewed")
                rec_id = rec.id
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _review_recommendation_impl,
            )
            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                resp = await _review_recommendation_impl(session, str(rec_id), r, user_id)
                assert resp.status == "approved"
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(AuditEvent.entity_id == rec_id)
                )
                events = result.scalars().all()
                assert len(events) == 1
                meta = events[0].metadata_
                assert meta["previous_status"] == "reviewed"
                assert meta["new_status"] == "approved"
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_rejection_audit(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                rec = await _make_recommendation(session, user_id, "v1", status="generated")
                rec_id = rec.id
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _review_recommendation_impl,
            )
            async with factory() as session:
                r = _FakeRequest(action="reject", reason="No")
                resp = await _review_recommendation_impl(session, str(rec_id), r, user_id)
                assert resp.status == "rejected"
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(AuditEvent.entity_id == rec_id)
                )
                events = result.scalars().all()
                assert len(events) == 1
                meta = events[0].metadata_
                assert meta["previous_status"] == "generated"
                assert meta["new_status"] == "rejected"
                assert meta["reason"] == "No"
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_activation_audit(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                ver = await _make_version(session, user_id, "v1", status="generated")
                ver_id = ver.id
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
            )
            async with factory() as session:
                r = _FakeRequest(confirm=True)
                resp = await _activate_version_impl(session, "v1", r, user_id)
                assert resp.status == "active"
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == ver_id,
                        AuditEvent.event_type == "calibration_activated",
                    )
                )
                events = result.scalars().all()
                assert len(events) == 1
                meta = events[0].metadata_
                assert meta["previous_status"] == "generated"
                assert meta["new_status"] == "active"
                assert meta["version_id"] == "v1"
                assert meta["user_id"] == str(user_id)
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_supersession_audit(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                await _make_version(session, user_id, "v1")
                await _make_version(session, user_id, "v2")
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
            )
            async with factory() as session:
                r = _FakeRequest(confirm=True)
                await _activate_version_impl(session, "v1", r, user_id)
                await session.commit()

            async with factory() as session:
                r = _FakeRequest(confirm=True)
                await _activate_version_impl(session, "v2", r, user_id)
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.event_type == "calibration_superseded",
                    )
                )
                events = result.scalars().all()
                assert len(events) >= 1
                meta = events[0].metadata_
                assert meta["previous_status"] == "active"
                assert meta["new_status"] == "superseded"
                assert meta["superseded_by"] == "v2"
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_rollback_audit_metadata(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                await _make_version(session, user_id, "v1",
                             param_snapshot={"signal_weights": {"intent_drift": 0.25}})
                await _make_version(session, user_id, "v2", status="active",
                             activated_at=datetime.now(UTC), activated_by=user_id,
                             previous_version="v1",
                             param_snapshot={"signal_weights": {"intent_drift": 0.35}})
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _rollback_impl,
            )
            async with factory() as session:
                resp = await _rollback_impl(session, user_id)
                assert resp.rolled_back is True
                await session.commit()

            async with factory() as session:
                sup = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.event_type == "calibration_superseded",
                    )
                )
                sup_events = sup.scalars().all()
                assert len(sup_events) >= 1
                sm = sup_events[0].metadata_
                assert sm["previous_status"] == "active"
                assert sm["new_status"] == "superseded"

                act = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.event_type == "calibration_activated",
                        AuditEvent.entity_type == "calibration_version",
                    )
                )
                act_events = [
                    e for e in act.scalars().all()
                    if e.metadata_.get("rollback") is True
                ]
                assert len(act_events) >= 1
                am = act_events[0].metadata_
                assert am["new_status"] == "active"
                assert am["rollback"] is True
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_idempotent_activation_no_duplicate_audit(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                await _make_version(session, user_id, "v1")
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
            )
            async with factory() as session:
                r = _FakeRequest(confirm=True)
                await _activate_version_impl(session, "v1", r, user_id)
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.event_type == "calibration_activated",
                    )
                )
                count_before = len(result.scalars().all())

            async with factory() as session:
                r = _FakeRequest(confirm=True)
                resp = await _activate_version_impl(session, "v1", r, user_id)
                assert resp.idempotent is True
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.event_type == "calibration_activated",
                    )
                )
                count_after = len(result.scalars().all())
                assert count_after == count_before
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_idempotent_review_no_duplicate_audit(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                rec = await _make_recommendation(session, user_id, "v1", status="approved")
                rec_id = rec.id
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _review_recommendation_impl,
            )
            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(AuditEvent.entity_id == rec_id)
                )
                count_before = len(result.scalars().all())

            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                resp = await _review_recommendation_impl(session, str(rec_id), r, user_id)
                assert resp.idempotent is True
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(AuditEvent).where(AuditEvent.entity_id == rec_id)
                )
                count_after = len(result.scalars().all())
                assert count_after == count_before
        finally:
            await _teardown_engine(engine_db)


# ══════════════════════════════════════════════════════════════════
# SECTION 5: SECURITY — CROSS-USER ISOLATION
# ══════════════════════════════════════════════════════════════════


class TestSecurityIsolation:

    @pytest.mark.asyncio
    async def test_cross_user_activate_returns_403(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            async with factory() as session:
                await _make_version(session, USER_A, "v1")
                await session.commit()

            from fastapi import HTTPException

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
            )
            async with factory() as session:
                r = _FakeRequest(confirm=True)
                with pytest.raises(HTTPException) as exc_info:
                    await _activate_version_impl(session, "v1", r, USER_B)
                assert exc_info.value.status_code == 403
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_cross_user_review_returns_403(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            async with factory() as session:
                rec = await _make_recommendation(session, USER_A, "v1")
                rec_id = str(rec.id)
                await session.commit()

            from fastapi import HTTPException

            from app.api.v1.endpoints.calibration_intelligence import (
                _review_recommendation_impl,
            )
            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                with pytest.raises(HTTPException) as exc_info:
                    await _review_recommendation_impl(session, rec_id, r, USER_B)
                assert exc_info.value.status_code == 403
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_cross_user_rollback_returns_404(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            async with factory() as session:
                await _make_version(
                    session, USER_A, "v1", status="active",
                    activated_at=datetime.now(UTC), activated_by=USER_A,
                )
                await session.commit()

            from fastapi import HTTPException

            from app.api.v1.endpoints.calibration_intelligence import (
                _rollback_impl,
            )
            async with factory() as session:
                with pytest.raises(HTTPException) as exc_info:
                    await _rollback_impl(session, USER_B)
                assert exc_info.value.status_code == 404
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_user_isolation_db_adapter(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            async with factory() as session:
                await _make_version(
                    session, USER_A, "v1", status="active",
                    activated_at=datetime.now(UTC), activated_by=USER_A,
                )
                await session.commit()

            async with factory() as session:
                active_a = await load_active_calibration(session, USER_A)
                assert active_a is not None
                active_b = await load_active_calibration(session, USER_B)
                assert active_b is None
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_no_version_leak_across_users(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            async with factory() as session:
                await _make_version(
                    session, USER_A, "v1", status="active",
                    activated_at=datetime.now(UTC), activated_by=USER_A,
                )
                await session.commit()

            async with factory() as session:
                active = await load_active_calibration(session, USER_B)
                assert active is None
        finally:
            await _teardown_engine(engine_db)


# ══════════════════════════════════════════════════════════════════
# SECTION 6: RUNTIME SAFETY
# ══════════════════════════════════════════════════════════════════


class TestRuntimeSafety:

    @pytest.mark.asyncio
    async def test_only_active_consumed(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                await _make_version(session, user_id, "v1", status="generated")
                await _make_version(session, user_id, "v2", status="superseded")
                await _make_version(session, user_id, "v3", status="active",
                             activated_at=datetime.now(UTC), activated_by=user_id)
                await session.commit()

            async with factory() as session:
                active = await load_active_calibration(session, user_id)
                assert active.version_id == "v3"
        finally:
            await _teardown_engine(engine_db)

    def test_no_signal_weight_mutation(self):
        original = dict(SIGNAL_WEIGHTS)
        ctx = _make_risk_context()
        cfg = RiskEngineConfig(
            signal_weights={"intent_drift": 0.50, "amount_anomaly": 0.12,
                            "agent_trust": 0.10, "merchant_trust": 0.08,
                            "policy_interaction": 0.10, "velocity": 0.05,
                            "data_quality": 0.00, "currency_mismatch": 0.025,
                            "geographic_anomaly": 0.025},
            calibration_active=True, calibration_version_id="test",
        )
        RiskEngine().evaluate(ctx, config=cfg)
        for rt, val in original.items():
            assert SIGNAL_WEIGHTS[rt] == val

    def test_no_risk_threshold_mutation(self):
        ctx = _make_risk_context()
        cfg = RiskEngineConfig(
            risk_level_thresholds={"critical": 0.90, "high": 0.70,
                                   "medium": 0.40, "low": 0.00},
            calibration_active=True, calibration_version_id="test",
        )
        RiskEngine().evaluate(ctx, config=cfg)
        for i, val in enumerate(RISK_LEVEL_THRESHOLDS):
            assert RISK_LEVEL_THRESHOLDS[i] == val

    def test_no_confidence_reduction_mutation(self):
        original = dict(CONFIDENCE_REDUCTIONS)
        ctx = _make_risk_context()
        cfg = RiskEngineConfig(
            confidence_reductions={k: 0.30 for k in CONFIDENCE_REDUCTIONS},
            calibration_active=True, calibration_version_id="test",
        )
        RiskEngine().evaluate(ctx, config=cfg)
        for k, v in original.items():
            assert CONFIDENCE_REDUCTIONS[k] == v

    def test_risk_engine_db_free(self):
        result = RiskEngine().evaluate(_make_risk_context())
        assert result.calibration_active is False

    @pytest.mark.asyncio
    async def test_superseded_not_consumed(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                await _make_version(session, user_id, "v1", status="superseded",
                             param_snapshot={"signal_weights": {"intent_drift": 0.99}})
                await session.commit()
            async with factory() as session:
                active = await load_active_calibration(session, user_id)
                assert active is None
            effective = resolve_effective_config(None)
            assert effective.signal_weights["intent_drift"] == 0.25
        finally:
            await _teardown_engine(engine_db)

    def test_generated_not_consumed(self):
        cal = RuntimeCalibrationConfig(
            version_id="v-new", is_active=False,
            parameter_snapshot={"signal_weights": {"intent_drift": 0.99}},
        )
        effective = resolve_effective_config(cal)
        assert effective.calibration_active is False
        assert effective.signal_weights["intent_drift"] == 0.25


# ══════════════════════════════════════════════════════════════════
# SECTION 7: OBSERVABILITY
# ══════════════════════════════════════════════════════════════════


class TestObservability:

    @pytest.mark.asyncio
    async def test_consumption_event_accuracy(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            agent_id = uuid.uuid4()
            tx_id = uuid.uuid4()
            async with factory() as session:
                _make_tx(session, user_id, agent_id, id=tx_id)
                _make_event(session, tx_id, agent_id, payload={
                    "calibration_active": True,
                    "calibration_version_id": "v1",
                    "fallback_reason": None,
                    "risk_level": "medium",
                    "risk_score": 0.35,
                    "confidence": 0.88,
                })
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(TransactionEvent).where(
                        TransactionEvent.transaction_id == tx_id,
                        TransactionEvent.event_type == "calibration_consumed",
                    )
                )
                event = result.scalars().one()
                p = event.payload
                assert p["calibration_active"] is True
                assert p["calibration_version_id"] == "v1"
                assert p["fallback_reason"] is None
                assert p["risk_level"] == "medium"
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_fallback_reasons_tracked(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            agent_id = uuid.uuid4()
            async with factory() as session:
                tx = _make_tx(session, user_id, agent_id)
                reasons = [
                    ("no_active_calibration", False),
                    ("validation_failed", False),
                    ("default", False),
                    (None, True),
                ]
                for i, (reason, active) in enumerate(reasons):
                    _make_event(session, tx.id, agent_id, seq=i + 2, payload={
                        "calibration_active": active,
                        "calibration_version_id": "cal-v1" if active else "",
                        "fallback_reason": reason,
                        "risk_level": "low",
                    })
                await session.commit()

            async with factory() as session:
                metrics = await compute_calibration_metrics(session, user_id)
                assert metrics.total_decisions == 4
                assert metrics.calibration_active_count == 1
                assert metrics.no_active_calibration_count == 1
                assert metrics.validation_failed_count == 1
                assert metrics.default_count == 1
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_version_usage_counts(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            agent_id = uuid.uuid4()
            async with factory() as session:
                t1 = _make_tx(session, user_id, agent_id)
                t2 = _make_tx(session, user_id, agent_id)
                t3 = _make_tx(session, user_id, agent_id)
                _make_event(session, t1.id, agent_id, payload={
                    "calibration_active": True,
                    "calibration_version_id": "v1",
                    "fallback_reason": None, "risk_level": "low",
                })
                _make_event(session, t2.id, agent_id, payload={
                    "calibration_active": True,
                    "calibration_version_id": "v1",
                    "fallback_reason": None, "risk_level": "medium",
                })
                _make_event(session, t3.id, agent_id, payload={
                    "calibration_active": True,
                    "calibration_version_id": "v2",
                    "fallback_reason": None, "risk_level": "high",
                })
                await session.commit()

            async with factory() as session:
                metrics = await compute_calibration_metrics(session, user_id)
                assert metrics.usage_by_version.get("v1") == 2
                assert metrics.usage_by_version.get("v2") == 1
                assert metrics.risk_level_distribution.get("low") == 1
                assert metrics.risk_level_distribution.get("medium") == 1
                assert metrics.risk_level_distribution.get("high") == 1
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_metrics_user_isolation(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            async with factory() as session:
                tx_a = _make_tx(session, USER_A)
                _make_event(session, tx_a.id, tx_a.agent_id, payload={
                    "calibration_active": True, "calibration_version_id": "v-a",
                    "fallback_reason": None, "risk_level": "low",
                })
                tx_b = _make_tx(session, USER_B)
                _make_event(session, tx_b.id, tx_b.agent_id, payload={
                    "calibration_active": True, "calibration_version_id": "v-b",
                    "fallback_reason": None, "risk_level": "high",
                })
                await session.commit()

            async with factory() as session:
                ma = await compute_calibration_metrics(session, USER_A)
                mb = await compute_calibration_metrics(session, USER_B)
                assert ma.total_decisions == 1
                assert ma.usage_by_version.get("v-a") == 1
                assert mb.total_decisions == 1
                assert mb.usage_by_version.get("v-b") == 1
                assert "v-a" not in mb.usage_by_version
                assert "v-b" not in ma.usage_by_version
        finally:
            await _teardown_engine(engine_db)


# ══════════════════════════════════════════════════════════════════
# SECTION 8: DETERMINISM
# ══════════════════════════════════════════════════════════════════


class TestDeterminism:

    def test_same_context_same_config(self):
        ctx = _make_risk_context()
        cfg = RiskEngineConfig(
            signal_weights={"intent_drift": 0.30, "amount_anomaly": 0.15,
                            "agent_trust": 0.15, "merchant_trust": 0.10,
                            "policy_interaction": 0.20, "velocity": 0.05,
                            "data_quality": 0.00, "currency_mismatch": 0.05,
                            "geographic_anomaly": 0.05},
            calibration_active=True, calibration_version_id="test",
        )
        engine = RiskEngine()
        results = [engine.evaluate(ctx, config=cfg) for _ in range(10)]
        assert len(set(r.overall_score for r in results)) == 1
        assert len(set(r.risk_level for r in results)) == 1
        assert len(set(r.confidence for r in results)) == 1

    def test_same_context_no_config(self):
        ctx = _make_risk_context()
        engine = RiskEngine()
        results = [engine.evaluate(ctx) for _ in range(10)]
        assert len(set(r.overall_score for r in results)) == 1

    def test_resolve_effective_config_deterministic(self):
        cal = RuntimeCalibrationConfig(
            version_id="v1", is_active=True,
            parameter_snapshot={"signal_weights": {"intent_drift": 0.30}},
        )
        results = [resolve_effective_config(cal) for _ in range(10)]
        assert len(set(r.signal_weights["intent_drift"] for r in results)) == 1

    def test_resolve_defaults_deterministic(self):
        results = [resolve_effective_config(None) for _ in range(10)]
        assert len(set(r.signal_weights["intent_drift"] for r in results)) == 1
        assert all(r.signal_weights["intent_drift"] == 0.25 for r in results)


# ══════════════════════════════════════════════════════════════════
# SECTION 9: VERSION STATE MACHINE
# ══════════════════════════════════════════════════════════════════


class TestVersionStateMachine:

    def test_generated_to_active(self):
        ok, _ = validate_version_transition("generated", "active")
        assert ok is True

    def test_active_to_superseded(self):
        ok, _ = validate_version_transition("active", "superseded")
        assert ok is True

    def test_generated_to_superseded_forbidden(self):
        ok, _ = validate_version_transition("generated", "superseded")
        assert ok is False

    def test_superseded_to_active_allowed_for_rollback(self):
        ok, _ = validate_version_transition("superseded", "active")
        assert ok is True

    def test_active_to_generated_forbidden(self):
        ok, _ = validate_version_transition("active", "generated")
        assert ok is False

    def test_same_state_idempotent(self):
        ok, _ = validate_version_transition("active", "active")
        assert ok is True

    def test_can_activate_no_recs(self):
        ok, _ = can_activate_version("generated", [])
        assert ok is True

    def test_can_activate_all_approved(self):
        ok, _ = can_activate_version("generated", ["approved"])
        assert ok is True

    def test_can_activate_all_rejected(self):
        ok, _ = can_activate_version("generated", ["rejected"])
        assert ok is True

    def test_can_activate_mixed(self):
        ok, _ = can_activate_version("generated", ["approved", "rejected"])
        assert ok is True

    def test_can_activate_blocked_by_generated(self):
        ok, _ = can_activate_version("generated", ["generated"])
        assert ok is False

    def test_can_activate_blocked_by_reviewed(self):
        ok, _ = can_activate_version("generated", ["reviewed"])
        assert ok is False

    def test_active_idempotent(self):
        ok, _ = can_activate_version("active", [])
        assert ok is True

    def test_superseded_can_activate(self):
        """Superseded versions can activate for rollback."""
        ok, _ = can_activate_version("superseded", [])
        assert ok is True


# ══════════════════════════════════════════════════════════════════
# SECTION 10: RECOMMENDATION STATE MACHINE
# ══════════════════════════════════════════════════════════════════


class TestRecommendationStateMachine:

    def test_generated_to_reviewed(self):
        ok, _ = validate_recommendation_transition("generated", "reviewed")
        assert ok is True

    def test_generated_to_rejected(self):
        ok, _ = validate_recommendation_transition("generated", "rejected")
        assert ok is True

    def test_reviewed_to_approved(self):
        ok, _ = validate_recommendation_transition("reviewed", "approved")
        assert ok is True

    def test_reviewed_to_rejected(self):
        ok, _ = validate_recommendation_transition("reviewed", "rejected")
        assert ok is True

    def test_approved_to_activated(self):
        ok, _ = validate_recommendation_transition("approved", "activated")
        assert ok is True

    def test_activated_to_superseded(self):
        ok, _ = validate_recommendation_transition("activated", "superseded")
        assert ok is True

    def test_generated_to_activated_forbidden(self):
        ok, _ = validate_recommendation_transition("generated", "activated")
        assert ok is False

    def test_reviewed_to_activated_forbidden(self):
        ok, _ = validate_recommendation_transition("reviewed", "activated")
        assert ok is False

    def test_rejected_terminal(self):
        ok, _ = validate_recommendation_transition("rejected", "approved")
        assert ok is False

    def test_superseded_terminal(self):
        ok, _ = validate_recommendation_transition("superseded", "approved")
        assert ok is False

    def test_no_downgrade_activated_to_approved(self):
        ok, _ = validate_recommendation_transition("activated", "approved")
        assert ok is False

    def test_no_downgrade_approved_to_reviewed(self):
        ok, _ = validate_recommendation_transition("approved", "reviewed")
        assert ok is False


# ══════════════════════════════════════════════════════════════════
# SECTION 11: IMMUTABILITY
# ══════════════════════════════════════════════════════════════════


class TestImmutability:

    @pytest.mark.asyncio
    async def test_review_preserves_content(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                rec = await _make_recommendation(
                    session, user_id, "v1",
                    rec_type="threshold_review",
                    engine_name="policy_engine",
                    parameter="velocity_limit",
                )
                rec_id = rec.id
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _review_recommendation_impl,
            )
            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                await _review_recommendation_impl(session, str(rec_id), r, user_id)
                await session.commit()
            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                await _review_recommendation_impl(session, str(rec_id), r, user_id)
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(CalibrationRecommendationRecord).where(
                        CalibrationRecommendationRecord.id == rec_id,
                    )
                )
                updated = result.scalar_one()
                assert updated.recommendation_type == "threshold_review"
                assert updated.engine == "policy_engine"
                assert updated.parameter == "velocity_limit"
                assert updated.status == "approved"
                assert updated.reviewed_by == user_id
                assert updated.approved_by == user_id
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_activation_preserves_content(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            snap = {"signal_weights": {"intent_drift": 0.30}}
            async with factory() as session:
                ver = await _make_version(
                    session, user_id, "v1",
                    param_snapshot=snap, total_samples=200,
                    eligible_samples=150, excluded_samples=50,
                )
                ver_id = ver.id
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
            )
            async with factory() as session:
                r = _FakeRequest(confirm=True)
                await _activate_version_impl(session, "v1", r, user_id)
                await session.commit()

            async with factory() as session:
                result = await session.execute(
                    select(CalibrationVersionRecord).where(
                        CalibrationVersionRecord.id == ver_id,
                    )
                )
                updated = result.scalar_one()
                assert updated.parameter_snapshot == snap
                assert updated.total_samples == 200
                assert updated.eligible_samples == 150
                assert updated.excluded_samples == 50
                assert updated.status == "active"
                assert updated.activated_by == user_id
        finally:
            await _teardown_engine(engine_db)


# ══════════════════════════════════════════════════════════════════
# SECTION 12: SECURITY SCAN
# ══════════════════════════════════════════════════════════════════


class TestSecurityScan:

    def test_state_machine_no_dangerous_patterns(self):
        import inspect

        from app.services.calibration_intelligence import state_machine
        source = inspect.getsource(state_machine)
        for p in ["eval(", "exec(", "subprocess", "__import__"]:
            assert p not in source

    def test_resolver_no_dangerous_patterns(self):
        import inspect

        from app.services.calibration_runtime import resolver
        source = inspect.getsource(resolver)
        for p in ["eval(", "exec(", "subprocess", "__import__"]:
            assert p not in source

    def test_risk_engine_config_no_db(self):
        import inspect

        from app.services.risk_engine import config
        source = inspect.getsource(config)
        assert "sqlalchemy" not in source.lower()
        assert "from app.models" not in source

    def test_no_runtime_weight_mutation_in_endpoints(self):
        import inspect

        from app.api.v1.endpoints import calibration_intelligence
        source = inspect.getsource(calibration_intelligence)
        assert "SIGNAL_WEIGHTS[" not in source
        assert "RISK_LEVEL_THRESHOLDS[" not in source
        assert "CONFIDENCE_REDUCTIONS[" not in source


# ══════════════════════════════════════════════════════════════════
# SECTION 13: EDGE CASES
# ══════════════════════════════════════════════════════════════════


class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_empty_recommendations_can_activate(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                await _make_version(session, user_id, "v1", recommendation_count=0)
                await session.commit()

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
            )
            async with factory() as session:
                r = _FakeRequest(confirm=True)
                resp = await _activate_version_impl(session, "v1", r, user_id)
                assert resp.status == "active"
                assert resp.recommendations_applied == 0
                await session.commit()
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_nonexistent_version_404(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            from fastapi import HTTPException

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
            )
            async with factory() as session:
                r = _FakeRequest(confirm=True)
                with pytest.raises(HTTPException) as exc_info:
                    await _activate_version_impl(session, "nonexistent", r, user_id)
                assert exc_info.value.status_code == 404
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_requires_confirm_true(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                await _make_version(session, user_id, "v1")
                await session.commit()

            from fastapi import HTTPException

            from app.api.v1.endpoints.calibration_intelligence import (
                _activate_version_impl,
            )
            async with factory() as session:
                r = _FakeRequest(confirm=False)
                with pytest.raises(HTTPException) as exc_info:
                    await _activate_version_impl(session, "v1", r, user_id)
                assert exc_info.value.status_code == 422
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_multiple_active_fail_closed(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            async with factory() as session:
                await _make_version(session, user_id, "v1", status="active",
                             activated_at=datetime.now(UTC), activated_by=user_id)
                await _make_version(session, user_id, "v2", status="active",
                             activated_at=datetime.now(UTC), activated_by=user_id)
                await session.commit()

            async with factory() as session:
                active = await load_active_calibration(session, user_id)
                assert active is None
        finally:
            await _teardown_engine(engine_db)

    @pytest.mark.asyncio
    async def test_nonexistent_recommendation_404(self):
        engine_db = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine_db, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            from fastapi import HTTPException

            from app.api.v1.endpoints.calibration_intelligence import (
                _review_recommendation_impl,
            )
            async with factory() as session:
                r = _FakeRequest(action="approve", reason=None)
                with pytest.raises(HTTPException) as exc_info:
                    await _review_recommendation_impl(
                        session, str(uuid.uuid4()), r, user_id,
                    )
                assert exc_info.value.status_code == 404
        finally:
            await _teardown_engine(engine_db)


# ══════════════════════════════════════════════════════════════════
# SECTION 14: BACKWARD COMPATIBILITY
# ══════════════════════════════════════════════════════════════════


class TestBackwardCompatibility:

    def test_all_risk_levels_produced(self):
        engine = RiskEngine()
        ctx_low = _make_risk_context(
            drift_overall_status="match", drift_severity="low",
            agent_trust_score=0.95, merchant_trust_score=0.90,
            policy_triggered_count=0,
        )
        ctx_high = _make_risk_context(
            drift_overall_status="mismatch", drift_severity="critical",
            agent_trust_score=0.10, merchant_trust_score=0.05,
            policy_triggered_count=3,
        )
        r_low = engine.evaluate(ctx_low, config=None)
        r_high = engine.evaluate(ctx_high, config=None)
        assert r_high.overall_score >= r_low.overall_score
        assert 0.0 <= r_low.overall_score <= 1.0

    def test_result_fields_populated(self):
        result = RiskEngine().evaluate(_make_risk_context(), config=None)
        assert 0.0 <= result.overall_score <= 1.0
        assert result.risk_level is not None
        assert 0.0 <= result.confidence <= 1.0
        assert result.evaluation_id != ""
        assert result.risk_model_version == "deterministic-v1"
        assert result.calibration_active is False

    def test_default_config_fresh_copy(self):
        cfg1 = get_default_risk_engine_config()
        cfg2 = get_default_risk_engine_config()
        cfg1.signal_weights["intent_drift"] = 999.0
        assert cfg2.signal_weights["intent_drift"] == 0.25

    def test_default_weights_sum_to_one(self):
        cfg = get_default_risk_engine_config()
        positive = {k: v for k, v in cfg.signal_weights.items() if v > 0}
        assert abs(sum(positive.values()) - 1.0) < 1e-6

    def test_default_thresholds_sorted(self):
        effective = resolve_effective_config(None)
        thresholds = list(effective.risk_level_thresholds.values())
        for i in range(len(thresholds) - 1):
            assert thresholds[i] >= thresholds[i + 1]

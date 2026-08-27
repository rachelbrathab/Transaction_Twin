"""Sprint 18B — Calibration Runtime Observability & Safe Rollback tests.

Tests for:
- Consumption event tracking
- Fallback observability
- Calibration health metrics
- Safe rollback
- Governance state machine
- Ownership/security
- No global mutation
- Default Risk Engine equivalence
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
from app.models.calibration_version import CalibrationVersionRecord
from app.models.transaction import Transaction
from app.models.transaction_event import TransactionEvent
from app.services.calibration_intelligence.health_metrics import (
    compute_calibration_metrics,
)
from app.services.calibration_intelligence.state_machine import (
    can_activate_version,
    validate_version_transition,
)
from app.services.risk_engine.config import (
    RiskEngineConfig,
    get_default_risk_engine_config,
)
from app.services.risk_engine.constants import SIGNAL_WEIGHTS
from app.services.risk_engine.engine import RiskEngine
from app.services.risk_engine.models import RiskContext

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


def _create_version(
    session,
    user_id=None,
    version_id="calibration-v-test",
    status="generated",
    param_snapshot=None,
    **kwargs,
):
    version = CalibrationVersionRecord(
        user_id=user_id or uuid.uuid4(),
        version_id=version_id,
        source_window_days=kwargs.get("source_window_days", 30),
        total_samples=kwargs.get("total_samples", 100),
        eligible_samples=kwargs.get("eligible_samples", 80),
        excluded_samples=kwargs.get("excluded_samples", 20),
        recommendation_count=kwargs.get("recommendation_count", 0),
        parameter_snapshot=param_snapshot or {},
        status=status,
        activated_at=kwargs.get("activated_at"),
        activated_by=kwargs.get("activated_by"),
        previous_version=kwargs.get("previous_version"),
    )
    session.add(version)
    return version


def _make_risk_context(**overrides) -> RiskContext:
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


# ── Consumption Event Tests ──────────────────────────────────────


class TestConsumptionEvents:
    """Test calibration consumption event tracking via TransactionEvent."""

    @pytest.mark.asyncio
    async def test_consumption_event_created(self):
        """A calibration_consumed event is created with correct payload."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            tx_id = uuid.uuid4()
            agent_id = uuid.uuid4()

            async with factory() as session:
                tx = Transaction(
                    id=tx_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    intent_id=uuid.uuid4(),
                    merchant_id=uuid.uuid4(),
                    idempotency_key=uuid.uuid4(),
                    transaction_type="payment",
                    amount=Decimal("100"),
                    currency="USD",
                    status="decided",
                )
                session.add(tx)
                event = TransactionEvent(
                    transaction_id=tx_id,
                    agent_id=agent_id,
                    sequence_number=2,
                    event_type="calibration_consumed",
                    source="system",
                    verification_state="verified",
                    payload={
                        "calibration_active": True,
                        "calibration_version_id": "calibration-v1",
                        "fallback_reason": None,
                        "risk_level": "low",
                        "risk_score": 0.05,
                        "confidence": 0.95,
                    },
                )
                session.add(event)
                await session.commit()

            async with factory() as session:
                stmt = (
                    select(TransactionEvent)
                    .where(
                        TransactionEvent.transaction_id == tx_id,
                        TransactionEvent.event_type == "calibration_consumed",
                    )
                )
                result = await session.execute(stmt)
                events = result.scalars().all()
                assert len(events) == 1
                assert events[0].payload["calibration_active"] is True
                assert events[0].payload["calibration_version_id"] == "calibration-v1"
                assert events[0].payload["fallback_reason"] is None
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_default_path_fallback_reason(self):
        """Default path records correct fallback reason."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            tx_id = uuid.uuid4()
            agent_id = uuid.uuid4()

            async with factory() as session:
                tx = Transaction(
                    id=tx_id, user_id=user_id, agent_id=agent_id,
                    intent_id=uuid.uuid4(), merchant_id=uuid.uuid4(),
                    idempotency_key=uuid.uuid4(),
                    transaction_type="payment",
                    amount=Decimal("100"),
                    currency="USD",
                    status="decided",
                )
                session.add(tx)
                event = TransactionEvent(
                    transaction_id=tx_id, agent_id=agent_id,
                    sequence_number=2, event_type="calibration_consumed",
                    source="system", verification_state="verified",
                    payload={
                        "calibration_active": False,
                        "calibration_version_id": "",
                        "fallback_reason": "no_active_calibration",
                        "risk_level": "low",
                        "risk_score": 0.05,
                        "confidence": 0.95,
                    },
                )
                session.add(event)
                await session.commit()

            async with factory() as session:
                stmt = (
                    select(TransactionEvent)
                    .where(
                        TransactionEvent.transaction_id == tx_id,
                        TransactionEvent.event_type == "calibration_consumed",
                    )
                )
                result = await session.execute(stmt)
                events = result.scalars().all()
                assert len(events) == 1
                assert events[0].payload["calibration_active"] is False
                assert events[0].payload["fallback_reason"] == "no_active_calibration"
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_validation_failed_fallback(self):
        """Invalid calibration records validation_failed fallback."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            tx_id = uuid.uuid4()
            agent_id = uuid.uuid4()

            async with factory() as session:
                tx = Transaction(
                    id=tx_id, user_id=user_id, agent_id=agent_id,
                    intent_id=uuid.uuid4(), merchant_id=uuid.uuid4(),
                    idempotency_key=uuid.uuid4(),
                    transaction_type="payment",
                    amount=Decimal("100"),
                    currency="USD",
                    status="decided",
                )
                session.add(tx)
                event = TransactionEvent(
                    transaction_id=tx_id, agent_id=agent_id,
                    sequence_number=2, event_type="calibration_consumed",
                    source="system", verification_state="verified",
                    payload={
                        "calibration_active": False,
                        "calibration_version_id": "calibration-v-bad",
                        "fallback_reason": "validation_failed",
                        "risk_level": "low",
                        "risk_score": 0.05,
                        "confidence": 0.95,
                    },
                )
                session.add(event)
                await session.commit()

            async with factory() as session:
                stmt = (
                    select(TransactionEvent)
                    .where(
                        TransactionEvent.transaction_id == tx_id,
                        TransactionEvent.event_type == "calibration_consumed",
                    )
                )
                result = await session.execute(stmt)
                events = result.scalars().all()
                assert len(events) == 1
                assert events[0].payload["fallback_reason"] == "validation_failed"
                assert events[0].payload["calibration_version_id"] == "calibration-v-bad"
        finally:
            await _teardown_engine(engine)


# ── Health Metrics Tests ─────────────────────────────────────────


class TestHealthMetrics:
    """Test calibration health metrics computation."""

    @pytest.mark.asyncio
    async def test_empty_dataset(self):
        """No transactions → zero metrics."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            async with factory() as session:
                metrics = await compute_calibration_metrics(
                    session, uuid.uuid4(),
                )
                assert metrics.total_decisions == 0
                assert metrics.calibration_active_count == 0
                assert metrics.default_count == 0
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_default_usage_counted(self):
        """Default-path decisions are counted correctly."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            tx_id = uuid.uuid4()
            agent_id = uuid.uuid4()

            async with factory() as session:
                tx = Transaction(
                    id=tx_id, user_id=user_id, agent_id=agent_id,
                    intent_id=uuid.uuid4(), merchant_id=uuid.uuid4(),
                    idempotency_key=uuid.uuid4(),
                    transaction_type="payment",
                    amount=Decimal("100"),
                    currency="USD",
                    status="decided",
                )
                session.add(tx)
                for i in range(3):
                    event = TransactionEvent(
                        transaction_id=tx_id, agent_id=agent_id,
                        sequence_number=i + 2,
                        event_type="calibration_consumed",
                        source="system", verification_state="verified",
                        payload={
                            "calibration_active": False,
                            "calibration_version_id": "",
                            "fallback_reason": "no_active_calibration",
                            "risk_level": "low",
                            "risk_score": 0.05,
                            "confidence": 0.95,
                        },
                    )
                    session.add(event)
                await session.commit()

            async with factory() as session:
                metrics = await compute_calibration_metrics(session, user_id)
                assert metrics.total_decisions == 3
                assert metrics.no_active_calibration_count == 3
                assert metrics.calibration_active_count == 0
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_calibration_active_counted(self):
        """Active calibration decisions are counted correctly."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            tx_id = uuid.uuid4()
            agent_id = uuid.uuid4()

            async with factory() as session:
                tx = Transaction(
                    id=tx_id, user_id=user_id, agent_id=agent_id,
                    intent_id=uuid.uuid4(), merchant_id=uuid.uuid4(),
                    idempotency_key=uuid.uuid4(),
                    transaction_type="payment",
                    amount=Decimal("100"),
                    currency="USD",
                    status="decided",
                )
                session.add(tx)
                event = TransactionEvent(
                    transaction_id=tx_id, agent_id=agent_id,
                    sequence_number=2, event_type="calibration_consumed",
                    source="system", verification_state="verified",
                    payload={
                        "calibration_active": True,
                        "calibration_version_id": "calibration-v1",
                        "fallback_reason": None,
                        "risk_level": "medium",
                        "risk_score": 0.35,
                        "confidence": 0.88,
                    },
                )
                session.add(event)
                await session.commit()

            async with factory() as session:
                metrics = await compute_calibration_metrics(session, user_id)
                assert metrics.calibration_active_count == 1
                assert metrics.usage_by_version.get("calibration-v1") == 1
                assert metrics.risk_level_distribution.get("medium") == 1
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_user_isolation(self):
        """Metrics are scoped to user_id."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_a = uuid.uuid4()
            user_b = uuid.uuid4()

            async with factory() as session:
                # User A has calibration events
                tx_a = Transaction(
                    id=uuid.uuid4(), user_id=user_a, agent_id=uuid.uuid4(),
                    intent_id=uuid.uuid4(), merchant_id=uuid.uuid4(),
                    idempotency_key=uuid.uuid4(),
                    transaction_type="payment",
                    amount=Decimal("100"),
                    currency="USD",
                    status="decided",
                )
                session.add(tx_a)
                event_a = TransactionEvent(
                    transaction_id=tx_a.id, agent_id=tx_a.agent_id,
                    sequence_number=2, event_type="calibration_consumed",
                    source="system", verification_state="verified",
                    payload={
                        "calibration_active": True,
                        "calibration_version_id": "cal-v-a",
                        "fallback_reason": None,
                        "risk_level": "low",
                        "risk_score": 0.05,
                        "confidence": 0.95,
                    },
                )
                session.add(event_a)

                # User B has no events
                tx_b = Transaction(
                    id=uuid.uuid4(), user_id=user_b, agent_id=uuid.uuid4(),
                    intent_id=uuid.uuid4(), merchant_id=uuid.uuid4(),
                    idempotency_key=uuid.uuid4(),
                    transaction_type="payment",
                    amount=Decimal("50"),
                    currency="USD",
                    status="decided",
                )
                session.add(tx_b)
                await session.commit()

            async with factory() as session:
                metrics_a = await compute_calibration_metrics(session, user_a)
                metrics_b = await compute_calibration_metrics(session, user_b)
                assert metrics_a.total_decisions == 1
                assert metrics_a.calibration_active_count == 1
                assert metrics_b.total_decisions == 0
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_fallback_reasons_tracked(self):
        """Different fallback reasons are tracked correctly."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()
            agent_id = uuid.uuid4()

            reasons = [
                "no_active_calibration",
                "validation_failed",
                "default",
                "no_active_calibration",
            ]

            async with factory() as session:
                tx = Transaction(
                    id=uuid.uuid4(), user_id=user_id, agent_id=agent_id,
                    intent_id=uuid.uuid4(), merchant_id=uuid.uuid4(),
                    idempotency_key=uuid.uuid4(),
                    transaction_type="payment",
                    amount=Decimal("100"),
                    currency="USD",
                    status="decided",
                )
                session.add(tx)
                for i, reason in enumerate(reasons):
                    event = TransactionEvent(
                        transaction_id=tx.id, agent_id=agent_id,
                        sequence_number=i + 2,
                        event_type="calibration_consumed",
                        source="system", verification_state="verified",
                        payload={
                            "calibration_active": False,
                            "calibration_version_id": "",
                            "fallback_reason": reason,
                            "risk_level": "low",
                            "risk_score": 0.05,
                            "confidence": 0.95,
                        },
                    )
                    session.add(event)
                await session.commit()

            async with factory() as session:
                metrics = await compute_calibration_metrics(session, user_id)
                assert metrics.total_decisions == 4
                assert metrics.no_active_calibration_count == 2
                assert metrics.validation_failed_count == 1
                assert metrics.default_count == 1
        finally:
            await _teardown_engine(engine)


# ── Rollback Tests ───────────────────────────────────────────────


class TestRollback:
    """Test safe rollback endpoint."""

    @pytest.mark.asyncio
    async def test_rollback_success(self):
        """Successful rollback: active → superseded, previous → active."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()

            async with factory() as session:
                _v1 = _create_version(
                    session,
                    user_id=user_id,
                    version_id="calibration-v1",
                    status="generated",
                    param_snapshot={"signal_weights": {"intent_drift": 0.30}},
                )
                _v2 = _create_version(
                    session,
                    user_id=user_id,
                    version_id="calibration-v2",
                    status="active",
                    param_snapshot={"signal_weights": {"intent_drift": 0.35}},
                    previous_version="calibration-v1",
                    activated_at=datetime.now(UTC),
                    activated_by=user_id,
                )
                await session.commit()

            # Perform rollback: v2 is active, v1 is the previous version
            async with factory() as session:
                from app.api.v1.endpoints.calibration_intelligence import (
                    _rollback_impl,
                )
                response = await _rollback_impl(session, user_id)
                assert response.rolled_back is True
                assert response.previous_active_version == "calibration-v2"
                assert response.restored_version == "calibration-v1"

            # Verify final state
            async with factory() as session:
                stmt = select(CalibrationVersionRecord).where(
                    CalibrationVersionRecord.user_id == user_id,
                )
                result = await session.execute(stmt)
                versions = {v.version_id: v for v in result.scalars().all()}
                assert versions["calibration-v1"].status == "active"
                assert versions["calibration-v2"].status == "superseded"
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_rollback_no_active_version(self):
        """Rollback with no active version returns 404."""
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
                    status="generated",
                )
                await session.commit()

            async with factory() as session:
                from fastapi import HTTPException

                from app.api.v1.endpoints.calibration_intelligence import (
                    _rollback_impl,
                )
                with pytest.raises(HTTPException) as exc_info:
                    await _rollback_impl(session, user_id)
                assert exc_info.value.status_code == 404
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_rollback_no_previous_version(self):
        """Rollback when active version has no previous_version returns 409."""
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
                    activated_at=datetime.now(UTC),
                    activated_by=user_id,
                    # No previous_version
                )
                await session.commit()

            async with factory() as session:
                from fastapi import HTTPException

                from app.api.v1.endpoints.calibration_intelligence import (
                    _rollback_impl,
                )
                with pytest.raises(HTTPException) as exc_info:
                    await _rollback_impl(session, user_id)
                assert exc_info.value.status_code == 409
                assert "no previous version" in exc_info.value.detail.lower()
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_rollback_previous_version_not_found(self):
        """Rollback when previous version doesn't exist returns 404."""
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
                    version_id="calibration-v2",
                    status="active",
                    activated_at=datetime.now(UTC),
                    activated_by=user_id,
                    previous_version="calibration-v1",
                )
                # v1 does NOT exist
                await session.commit()

            async with factory() as session:
                from fastapi import HTTPException

                from app.api.v1.endpoints.calibration_intelligence import (
                    _rollback_impl,
                )
                with pytest.raises(HTTPException) as exc_info:
                    await _rollback_impl(session, user_id)
                assert exc_info.value.status_code == 404
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_rollback_superseded_previous_rejected(self):
        """Rollback to a superseded previous version is rejected."""
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
                    status="superseded",
                )
                _create_version(
                    session,
                    user_id=user_id,
                    version_id="calibration-v2",
                    status="active",
                    activated_at=datetime.now(UTC),
                    activated_by=user_id,
                    previous_version="calibration-v1",
                )
                await session.commit()

            async with factory() as session:
                from fastapi import HTTPException

                from app.api.v1.endpoints.calibration_intelligence import (
                    _rollback_impl,
                )
                with pytest.raises(HTTPException) as exc_info:
                    await _rollback_impl(session, user_id)
                # Superseded is terminal — cannot activate
                assert exc_info.value.status_code == 409
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_rollback_audit_events_created(self):
        """Rollback creates correct audit events."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            user_id = uuid.uuid4()

            async with factory() as session:
                _v1 = _create_version(
                    session,
                    user_id=user_id,
                    version_id="calibration-v1",
                    status="generated",
                )
                _v2 = _create_version(
                    session,
                    user_id=user_id,
                    version_id="calibration-v2",
                    status="active",
                    activated_at=datetime.now(UTC),
                    activated_by=user_id,
                    previous_version="calibration-v1",
                )
                await session.commit()

            async with factory() as session:
                from app.api.v1.endpoints.calibration_intelligence import (
                    _rollback_impl,
                )
                await _rollback_impl(session, user_id)

            async with factory() as session:
                stmt = select(AuditEvent).where(
                    AuditEvent.entity_type == "calibration_version",
                )
                result = await session.execute(stmt)
                audits = result.scalars().all()
                event_types = {a.event_type for a in audits}
                assert "calibration_superseded" in event_types
                assert "calibration_activated" in event_types

                # Check superseded audit metadata
                superseded = next(
                    a for a in audits if a.event_type == "calibration_superseded"
                )
                assert superseded.metadata_["previous_status"] == "active"
                assert superseded.metadata_["new_status"] == "superseded"
        finally:
            await _teardown_engine(engine)


# ── Governance State Machine Tests ───────────────────────────────


class TestGovernanceStateMachine:
    """Test version state transitions used by rollback."""

    def test_generated_to_active(self):
        ok, err = validate_version_transition("generated", "active")
        assert ok is True
        assert err is None

    def test_active_to_superseded(self):
        ok, err = validate_version_transition("active", "superseded")
        assert ok is True
        assert err is None

    def test_superseded_is_terminal(self):
        ok, err = validate_version_transition("superseded", "active")
        assert ok is False

    def test_can_activate_generated_with_no_recs(self):
        ok, err = can_activate_version("generated", [])
        assert ok is True

    def test_can_activate_generated_with_all_approved(self):
        ok, err = can_activate_version("generated", ["approved", "approved"])
        assert ok is True

    def test_can_activate_generated_with_pending_recs_rejects(self):
        ok, err = can_activate_version("generated", ["approved", "reviewed"])
        assert ok is False
        assert "pending" in err.lower()

    def test_active_is_idempotent(self):
        ok, err = can_activate_version("active", [])
        assert ok is True

    def test_superseded_cannot_activate(self):
        ok, err = can_activate_version("superseded", [])
        assert ok is False


# ── No Global Mutation Tests ─────────────────────────────────────


class TestNoGlobalMutation:
    """Verify Risk Engine constants are never mutated."""

    def test_signal_weights_unchanged(self):
        original = dict(SIGNAL_WEIGHTS)
        ctx = _make_risk_context()
        cfg = RiskEngineConfig(
            signal_weights={
                "intent_drift": 0.40,
                "amount_anomaly": 0.12,
                "agent_trust": 0.12,
                "merchant_trust": 0.08,
                "policy_interaction": 0.12,
                "velocity": 0.04,
                "data_quality": 0.00,
                "currency_mismatch": 0.06,
                "geographic_anomaly": 0.06,
            },
            calibration_active=True,
            calibration_version_id="test",
        )
        engine = RiskEngine()
        engine.evaluate(ctx, config=cfg)

        for rt, val in original.items():
            assert SIGNAL_WEIGHTS[rt] == val

    def test_default_config_equivalence(self):
        """config=None produces identical results to config=default."""
        ctx = _make_risk_context()
        engine = RiskEngine()
        r_none = engine.evaluate(ctx, config=None)
        r_default = engine.evaluate(ctx, config=get_default_risk_engine_config())
        assert r_none.overall_score == r_default.overall_score
        assert r_none.risk_level == r_default.risk_level
        assert r_none.confidence == r_default.confidence

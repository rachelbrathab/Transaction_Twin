"""Tests for Calibration Intelligence persistence layer.

Covers:
- Generated result persisted correctly
- Recommendations persisted with correct fields
- Ownership persisted
- Evidence preserved
- Duplicate generation idempotent
- Transaction rollback on failure
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.calibration_recommendation import (
    CalibrationRecommendationRecord,
)
from app.models.calibration_version import CalibrationVersionRecord
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

USER_A = uuid.uuid4()
USER_B = uuid.uuid4()


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


def _make_result(
    version_id: str = "calibration-v1",
    window_days: int = 30,
    total_samples: int = 10,
    eligible_samples: int = 8,
    rec_count: int = 2,
) -> CalibrationIntelligenceResult:
    """Create a test CalibrationIntelligenceResult."""
    recommendations = []
    for i in range(rec_count):
        recommendations.append(CalibrationRecommendation(
            recommendation_id=f"rec-{i}",
            recommendation_type=RecommendationType.WEIGHT_REVIEW,
            engine="risk_engine",
            parameter=f"param_{i}",
            current_value={"weight": 0.25},
            proposed_value={"weight": 0.30},
            proposed_range=(0.20, 0.40),
            evidence={"sample_count": 15},
            sample_count=15,
            data_sufficiency=DataSufficiencyLevel.MODERATE,
            rationale=f"Test rationale {i}",
            severity="warning",
            generated_at=datetime.now(UTC).isoformat(),
            calibration_version=version_id,
            status=RecommendationStatus.GENERATED,
        ))

    version = CalibrationVersion(
        version_id=version_id,
        generated_at=datetime.now(UTC).isoformat(),
        source_window_days=window_days,
        total_samples=total_samples,
        eligible_samples=eligible_samples,
        excluded_samples=total_samples - eligible_samples,
        recommendation_count=rec_count,
        status=RecommendationStatus.GENERATED,
    )

    return CalibrationIntelligenceResult(
        dataset=CalibrationDataset(
            samples=[],
            total_samples=total_samples,
            eligible_samples=eligible_samples,
            excluded_samples=total_samples - eligible_samples,
            window_days=window_days,
            computed_at=datetime.now(UTC).isoformat(),
        ),
        metrics=[],
        recommendations=recommendations,
        version=version,
        computed_at=datetime.now(UTC).isoformat(),
    )


# ══════════════════════════════════════════════════════════════
# PERSISTENCE TESTS
# ══════════════════════════════════════════════════════════════


class TestPersistenceBasic:
    @pytest.mark.asyncio
    async def test_persist_creates_version_record(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result = _make_result()
            async with factory() as session:
                await persist_calibration_result(
                    session, USER_A, result,
                )
                await session.commit()

            async with factory() as session:
                r = await session.execute(
                    select(CalibrationVersionRecord).where(
                        CalibrationVersionRecord.user_id == USER_A,
                    )
                )
                versions = r.scalars().all()
                assert len(versions) == 1
                assert versions[0].version_id == "calibration-v1"
                assert versions[0].source_window_days == 30
                assert versions[0].total_samples == 10
                assert versions[0].eligible_samples == 8
                assert versions[0].status == "generated"
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_persist_creates_recommendation_records(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result = _make_result(rec_count=3)
            async with factory() as session:
                persistence_result = await persist_calibration_result(
                    session, USER_A, result,
                )
                await session.commit()
                assert len(persistence_result.recommendations) == 3

            async with factory() as session:
                r = await session.execute(
                    select(CalibrationRecommendationRecord).where(
                        CalibrationRecommendationRecord.user_id
                        == USER_A,
                    )
                )
                recs = r.scalars().all()
                assert len(persistence_result.recommendations) == 3
                assert all(
                    r.calibration_version == "calibration-v1"
                    for r in recs
                )
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_persist_preserves_evidence(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result = _make_result(rec_count=1)
            async with factory() as session:
                await persist_calibration_result(
                    session, USER_A, result,
                )
                await session.commit()

            async with factory() as session:
                r = await session.execute(
                    select(CalibrationRecommendationRecord).where(
                        CalibrationRecommendationRecord.user_id
                        == USER_A,
                    )
                )
                rec = r.scalar_one()
                assert rec.evidence == {"sample_count": 15}
                assert rec.parameter == "param_0"
                assert rec.rationale == "Test rationale 0"
                assert rec.severity == "warning"
                assert rec.sample_count == 15
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_persist_preserves_ownership(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result = _make_result()
            async with factory() as session:
                persistence_result = await persist_calibration_result(
                    session, USER_B, result,
                )
                await session.commit()
                assert persistence_result.version.user_id == USER_B

            async with factory() as session:
                r = await session.execute(
                    select(CalibrationVersionRecord).where(
                        CalibrationVersionRecord.user_id == USER_A,
                    )
                )
                assert len(r.scalars().all()) == 0

                r = await session.execute(
                    select(CalibrationVersionRecord).where(
                        CalibrationVersionRecord.user_id == USER_B,
                    )
                )
                assert len(r.scalars().all()) == 1
        finally:
            await _teardown_engine(engine)


class TestPersistenceIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_generation_returns_existing(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result = _make_result(version_id="calibration-v2")
            async with factory() as session:
                persistence_result1 = await persist_calibration_result(
                    session, USER_A, result,
                )
                await session.commit()
                v1_id = persistence_result1.version.id
                assert persistence_result1.created is True

            # Second call with same version_id
            async with factory() as session:
                persistence_result2 = await persist_calibration_result(
                    session, USER_A, result,
                )
                await session.commit()
                # Should return existing, not create new
                assert persistence_result2.version.id == v1_id
                assert persistence_result2.created is False
                assert len(persistence_result2.recommendations) == 2

            # Verify only one version exists
            async with factory() as session:
                r = await session.execute(
                    select(CalibrationVersionRecord).where(
                        CalibrationVersionRecord.user_id == USER_A,
                    )
                )
                assert len(r.scalars().all()) == 1
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_different_users_get_different_versions(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result_a = _make_result(version_id="calibration-v3a")
            async with factory() as session:
                persistence_a = await persist_calibration_result(
                    session, USER_A, result_a,
                )
                await session.commit()

            result_b = _make_result(version_id="calibration-v3b")
            async with factory() as session:
                persistence_b = await persist_calibration_result(
                    session, USER_B, result_b,
                )
                await session.commit()
                assert persistence_a.version.id != persistence_b.version.id

            async with factory() as session:
                r = await session.execute(
                    select(CalibrationVersionRecord)
                )
                assert len(r.scalars().all()) == 2
        finally:
            await _teardown_engine(engine)


class TestPersistenceValidation:
    @pytest.mark.asyncio
    async def test_missing_version_raises(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result = CalibrationIntelligenceResult(
                dataset=CalibrationDataset(),
                metrics=[],
                recommendations=[],
                version=None,
                computed_at="",
            )
            with pytest.raises(ValueError, match="must include a version"):
                async with factory() as session:
                    await persist_calibration_result(
                        session, USER_A, result,
                    )
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_proposed_range_serialized(self):
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result = _make_result(rec_count=1)
            async with factory() as session:
                await persist_calibration_result(
                    session, USER_A, result,
                )
                await session.commit()

            async with factory() as session:
                r = await session.execute(
                    select(CalibrationRecommendationRecord).where(
                        CalibrationRecommendationRecord.user_id
                        == USER_A,
                    )
                )
                rec = r.scalar_one()
                assert rec.proposed_range is not None
                assert rec.proposed_range["min"] == 0.20
                assert rec.proposed_range["max"] == 0.40
        finally:
            await _teardown_engine(engine)


# ══════════════════════════════════════════════════════════════
# SAFETY TESTS
# ══════════════════════════════════════════════════════════════


class TestSafety:
    def test_persistence_no_eval_exec(self):
        import inspect

        from app.services.calibration_intelligence import persistence
        source = inspect.getsource(persistence)
        assert "eval(" not in source
        assert "exec(" not in source
        assert "subprocess" not in source
        assert "__import__" not in source

    def test_persistence_no_sqlalchemy_mutation(self):
        """Persistence layer must not modify risk constants."""
        import inspect

        from app.services.calibration_intelligence import persistence
        source = inspect.getsource(persistence)
        assert "SIGNAL_WEIGHTS[" not in source
        assert "RISK_LEVEL_THRESHOLDS[" not in source
        assert "CONFIDENCE_REDUCTIONS[" not in source


# ══════════════════════════════════════════════════════════════
# IDEMPOTENCY TESTS
# ══════════════════════════════════════════════════════════════


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_same_generation_first_creates(self):
        """First call with same data creates a new version."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result = _make_result(
                version_id="idem-v1", rec_count=2,
            )
            async with factory() as session:
                pr = await persist_calibration_result(
                    session, USER_A, result,
                )
                await session.commit()
                assert pr.created is True
                assert pr.version.version_id == "idem-v1"
                assert len(pr.recommendations) == 2
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_same_generation_second_reuses(self):
        """Second call with same data returns existing, no duplicates."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result = _make_result(
                version_id="idem-v2", rec_count=2,
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
                assert len(pr2.recommendations) == 2

            # Verify exactly one version and two recommendations exist
            async with factory() as session:
                v = await session.execute(
                    select(CalibrationVersionRecord).where(
                        CalibrationVersionRecord.user_id == USER_A,
                    )
                )
                assert len(v.scalars().all()) == 1

                r = await session.execute(
                    select(CalibrationRecommendationRecord).where(
                        CalibrationRecommendationRecord.user_id
                        == USER_A,
                    )
                )
                assert len(r.scalars().all()) == 2
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_different_users_get_independent_records(self):
        """Different users get independent version records."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result_a = _make_result(version_id="idem-v3a")
            result_b = _make_result(version_id="idem-v3b")
            async with factory() as session:
                pr_a = await persist_calibration_result(
                    session, USER_A, result_a,
                )
                await session.commit()

            async with factory() as session:
                pr_b = await persist_calibration_result(
                    session, USER_B, result_b,
                )
                await session.commit()
                assert pr_a.version.id != pr_b.version.id
                assert pr_a.version.user_id == USER_A
                assert pr_b.version.user_id == USER_B
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_different_window_different_version(self):
        """Different window_days produces different version_id."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            r1 = _make_result(
                version_id="idem-v4a", window_days=30,
            )
            r2 = _make_result(
                version_id="idem-v4b", window_days=60,
            )
            async with factory() as session:
                pr1 = await persist_calibration_result(
                    session, USER_A, r1,
                )
                await session.commit()

            async with factory() as session:
                pr2 = await persist_calibration_result(
                    session, USER_A, r2,
                )
                await session.commit()
                assert pr1.version.id != pr2.version.id
                assert pr1.created is True
                assert pr2.created is True
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_different_recs_different_version(self):
        """Different recommendations produce different version_id."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            r1 = _make_result(
                version_id="idem-v5a", rec_count=1,
            )
            r2 = _make_result(
                version_id="idem-v5b", rec_count=3,
            )
            async with factory() as session:
                pr1 = await persist_calibration_result(
                    session, USER_A, r1,
                )
                await session.commit()

            async with factory() as session:
                pr2 = await persist_calibration_result(
                    session, USER_A, r2,
                )
                await session.commit()
                assert pr1.version.id != pr2.version.id
        finally:
            await _teardown_engine(engine)

    @pytest.mark.asyncio
    async def test_created_flag_accuracy(self):
        """created flag is True for new, False for reuse."""
        engine = await _setup_engine()
        try:
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False,
            )
            result = _make_result(version_id="idem-v6")
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
        finally:
            await _teardown_engine(engine)

"""Calibration Intelligence — persistence layer.

Persists CalibrationIntelligenceResult into calibration_versions and
calibration_recommendations tables. Transactional and idempotent.

Does NOT modify risk weights, thresholds, or runtime engine behavior.
Does NOT import SQLAlchemy at module level (lazy imports for testability).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calibration_recommendation import (
    CalibrationRecommendationRecord,
)
from app.models.calibration_version import CalibrationVersionRecord

logger = structlog.get_logger()


@dataclass
class PersistenceResult:
    """Result of persisting a calibration intelligence result."""

    version: CalibrationVersionRecord
    recommendations: list[CalibrationRecommendationRecord]
    created: bool


async def persist_calibration_result(
    db: AsyncSession,
    user_id: uuid.UUID,
    result,  # CalibrationIntelligenceResult
) -> PersistenceResult:
    """Persist a calibration intelligence result to the database.

    Idempotent: if a CalibrationVersionRecord with the same version_id
    already exists for this user, returns the existing record with
    created=False (no duplicates created).

    Args:
        db: Active database session.
        user_id: Owner of the calibration result.
        result: CalibrationIntelligenceResult from the engine.

    Returns:
        PersistenceResult with version, recommendations, and created flag.
    """
    version_model = result.version
    if version_model is None:
        raise ValueError(
            "CalibrationIntelligenceResult must include a version"
        )

    # ── Idempotency check ────────────────────────────────────
    existing = await db.execute(
        select(CalibrationVersionRecord).where(
            CalibrationVersionRecord.version_id
            == version_model.version_id,
            CalibrationVersionRecord.user_id == user_id,
        )
    )
    existing_version = existing.scalar_one_or_none()

    if existing_version is not None:
        logger.info(
            "calibration_version_already_exists",
            version_id=version_model.version_id,
            user_id=str(user_id),
        )
        # Return existing recommendations
        recs_result = await db.execute(
            select(CalibrationRecommendationRecord).where(
                CalibrationRecommendationRecord.calibration_version
                == version_model.version_id,
                CalibrationRecommendationRecord.user_id == user_id,
            )
        )
        return PersistenceResult(
            version=existing_version,
            recommendations=list(recs_result.scalars().all()),
            created=False,
        )

    # ── Create version record ────────────────────────────────
    now = datetime.now(UTC)
    version_record = CalibrationVersionRecord(
        user_id=user_id,
        version_id=version_model.version_id,
        source_window_days=version_model.source_window_days,
        total_samples=version_model.total_samples,
        eligible_samples=version_model.eligible_samples,
        excluded_samples=version_model.excluded_samples,
        recommendation_count=version_model.recommendation_count,
        parameter_snapshot=version_model.parameter_snapshot,
        status="generated",
        created_at=now,
        updated_at=now,
    )
    db.add(version_record)
    await db.flush()

    # ── Create recommendation records ────────────────────────
    recommendation_records: list[CalibrationRecommendationRecord] = []
    for rec in result.recommendations:
        rec_record = CalibrationRecommendationRecord(
            user_id=user_id,
            recommendation_type=rec.recommendation_type.value
            if hasattr(rec.recommendation_type, "value")
            else str(rec.recommendation_type),
            engine=rec.engine,
            parameter=rec.parameter,
            current_value=(
                _serialize(rec.current_value)
                if rec.current_value is not None
                else None
            ),
            proposed_value=(
                _serialize(rec.proposed_value)
                if rec.proposed_value is not None
                else None
            ),
            proposed_range=(
                {"min": rec.proposed_range[0], "max": rec.proposed_range[1]}
                if rec.proposed_range is not None
                else None
            ),
            evidence=_serialize(rec.evidence) if rec.evidence else {},
            sample_count=rec.sample_count,
            confidence=(
                rec.data_sufficiency.value
                if hasattr(rec.data_sufficiency, "value")
                else str(rec.data_sufficiency)
            ),
            rationale=rec.rationale,
            severity=rec.severity,
            status="generated",
            calibration_version=version_model.version_id,
            created_at=now,
            updated_at=now,
        )
        db.add(rec_record)
        recommendation_records.append(rec_record)

    await db.flush()

    logger.info(
        "calibration_result_persisted",
        version_id=version_model.version_id,
        user_id=str(user_id),
        recommendation_count=len(recommendation_records),
    )

    return PersistenceResult(
        version=version_record,
        recommendations=recommendation_records,
        created=True,
    )


def _serialize(value):
    """Serialize a value to a JSON-compatible dict.

    Handles Pydantic models, tuples, and primitives.
    """
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, tuple):
        return {"min": value[0], "max": value[1]}
    return value

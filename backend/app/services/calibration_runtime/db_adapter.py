"""Calibration Runtime — database adapter.

Thin async adapter that loads the active calibration version
from the database. Separates DB access from the pure resolver.

This module:
- queries only ACTIVE calibration versions
- scopes by user_id
- returns at most one active version
- never loads another user's calibration
- never mutates database state
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calibration_version import CalibrationVersionRecord
from app.services.calibration_runtime.models import RuntimeCalibrationConfig

logger = structlog.get_logger()


async def load_active_calibration(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> RuntimeCalibrationConfig | None:
    """Load the active calibration version for a user.

    If multiple active versions somehow exist (data integrity issue),
    fails safely by returning None rather than choosing arbitrarily.

    Args:
        db: Database session.
        user_id: The user who owns the calibration.

    Returns:
        RuntimeCalibrationConfig with the active calibration data,
        or None if no active calibration exists.
    """
    stmt = (
        select(CalibrationVersionRecord)
        .where(
            CalibrationVersionRecord.user_id == user_id,
            CalibrationVersionRecord.status == "active",
        )
        .order_by(CalibrationVersionRecord.activated_at.desc())
    )

    result = await db.execute(stmt)
    records = list(result.scalars().all())

    if not records:
        return None

    if len(records) > 1:
        # Data integrity issue — multiple active versions for one user.
        # Log a warning and return None rather than choosing arbitrarily.
        logger.warning(
            "multiple_active_calibration_versions",
            user_id=str(user_id),
            count=len(records),
            version_ids=[r.version_id for r in records],
        )
        return None

    record = records[0]
    return RuntimeCalibrationConfig(
        version_id=record.version_id,
        source_window_days=record.source_window_days,
        parameter_snapshot=record.parameter_snapshot or {},
        is_active=True,
        activated_at=record.activated_at.isoformat() if record.activated_at else None,
    )


async def load_calibration_version_by_id(
    db: AsyncSession,
    user_id: uuid.UUID,
    version_id: str,
) -> RuntimeCalibrationConfig | None:
    """Load a specific calibration version for a user.

    Args:
        db: Database session.
        user_id: The user who owns the calibration.
        version_id: The version identifier.

    Returns:
        RuntimeCalibrationConfig or None if not found.
    """
    stmt = (
        select(CalibrationVersionRecord)
        .where(
            CalibrationVersionRecord.user_id == user_id,
            CalibrationVersionRecord.version_id == version_id,
        )
    )

    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        return None

    return RuntimeCalibrationConfig(
        version_id=record.version_id,
        source_window_days=record.source_window_days,
        parameter_snapshot=record.parameter_snapshot or {},
        is_active=record.status == "active",
        activated_at=record.activated_at.isoformat() if record.activated_at else None,
    )

"""Calibration Intelligence — health metrics.

Provides deterministic, read-only, ownership-scoped metrics
for calibration usage and fallback tracking.

All functions are pure — no side effects, no mutation.
Queries are bounded and ownership-scoped.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.models.transaction_event import TransactionEvent


@dataclass(frozen=True)
class CalibrationMetrics:
    """Read-only calibration health metrics for a user."""

    total_decisions: int = 0
    calibration_active_count: int = 0
    default_count: int = 0
    validation_failed_count: int = 0
    no_active_calibration_count: int = 0
    usage_by_version: dict[str, int] = field(default_factory=dict)
    risk_level_distribution: dict[str, int] = field(default_factory=dict)


async def compute_calibration_metrics(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 10000,
) -> CalibrationMetrics:
    """Compute calibration health metrics for a user.

    Queries are bounded by limit and scoped by user_id.
    All results are deterministic for the same database state.

    Args:
        db: Database session.
        user_id: The user whose metrics to compute.
        limit: Maximum number of decisions to analyze (bounded).

    Returns:
        CalibrationMetrics with usage statistics.
    """
    # Get transaction IDs for this user
    tx_stmt = (
        select(Transaction.id)
        .where(Transaction.user_id == user_id)
        .limit(limit)
    )
    tx_result = await db.execute(tx_stmt)
    tx_ids = [row[0] for row in tx_result.all()]

    if not tx_ids:
        return CalibrationMetrics()

    # Query calibration consumption events for these transactions
    event_stmt = (
        select(TransactionEvent.payload)
        .where(
            TransactionEvent.transaction_id.in_(tx_ids),
            TransactionEvent.event_type == "calibration_consumed",
        )
    )
    event_result = await db.execute(event_stmt)
    events = [row[0] for row in event_result.all() if row[0] is not None]

    total = len(events)
    active_count = 0
    default_count = 0
    validation_failed_count = 0
    no_active_count = 0
    usage_by_version: dict[str, int] = {}
    risk_levels: dict[str, int] = {}

    for payload in events:
        cal_active = payload.get("calibration_active", False)
        version_id = payload.get("calibration_version_id", "")
        fallback = payload.get("fallback_reason")
        risk_level = payload.get("risk_level", "unknown")

        if cal_active:
            active_count += 1
            if version_id:
                usage_by_version[version_id] = (
                    usage_by_version.get(version_id, 0) + 1
                )
        else:
            if fallback == "validation_failed":
                validation_failed_count += 1
            elif fallback == "no_active_calibration":
                no_active_count += 1
            else:
                default_count += 1

        risk_levels[risk_level] = risk_levels.get(risk_level, 0) + 1

    return CalibrationMetrics(
        total_decisions=total,
        calibration_active_count=active_count,
        default_count=default_count,
        validation_failed_count=validation_failed_count,
        no_active_calibration_count=no_active_count,
        usage_by_version=usage_by_version,
        risk_level_distribution=risk_levels,
    )

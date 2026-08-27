"""Calibration Version model — versioned calibration snapshots."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, CompatibleJSONB


class CalibrationVersionRecord(Base):
    """A versioned calibration snapshot persisted in the database.

    Maps to the calibration_versions table created by migration 004.
    """

    __tablename__ = "calibration_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_id: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True,
    )
    source_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    total_samples: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    eligible_samples: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    excluded_samples: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    recommendation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    parameter_snapshot: Mapped[dict | None] = mapped_column(
        CompatibleJSONB(), nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    previous_version: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="generated",
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

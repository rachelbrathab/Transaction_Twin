"""Calibration Recommendation model — advisory calibration recommendations."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, CompatibleJSONB


class CalibrationRecommendationRecord(Base):
    """An advisory calibration recommendation persisted in the database.

    Maps to the calibration_recommendations table created by migration 004.
    Content fields are immutable after creation.
    Only governance fields (status, reviewed_*, approved_*, etc.) may change.
    """

    __tablename__ = "calibration_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    recommendation_type: Mapped[str] = mapped_column(
        String(100), nullable=False,
    )
    engine: Mapped[str] = mapped_column(
        String(100), nullable=False,
    )
    parameter: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    current_value: Mapped[dict | None] = mapped_column(
        CompatibleJSONB(), nullable=True,
    )
    proposed_value: Mapped[dict | None] = mapped_column(
        CompatibleJSONB(), nullable=True,
    )
    proposed_range: Mapped[dict | None] = mapped_column(
        CompatibleJSONB(), nullable=True,
    )
    evidence: Mapped[dict] = mapped_column(
        CompatibleJSONB(), nullable=False, server_default="{}",
    )
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    confidence: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="insufficient",
    )
    rationale: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="info",
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="generated",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    calibration_version: Mapped[str] = mapped_column(
        String(100), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

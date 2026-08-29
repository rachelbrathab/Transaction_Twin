"""Merchant model — merchant information for risk evaluation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, CompatibleJSONB


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_reference: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(3), nullable=True)
    trust_score: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", CompatibleJSONB(), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # Relationships
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="merchant")  # noqa: F821

    __table_args__ = (
        CheckConstraint(
            "trust_score IS NULL OR (trust_score >= 0 AND trust_score <= 1)",
            name="ck_merchants_trust_score_range",
        ),
    )

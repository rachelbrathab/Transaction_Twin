"""Intent model — what the user asked the agent to accomplish."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, CompatibleJSONB


class Intent(Base):
    __tablename__ = "intents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    original_request: Mapped[str] = mapped_column(Text, nullable=False)
    structured_intent: Mapped[dict | None] = mapped_column(CompatibleJSONB(), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="active")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    min_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    category_constraints: Mapped[dict | None] = mapped_column(CompatibleJSONB(), nullable=True)
    merchant_constraints: Mapped[dict | None] = mapped_column(CompatibleJSONB(), nullable=True)
    geographic_constraints: Mapped[dict | None] = mapped_column(CompatibleJSONB(), nullable=True)
    authorization_scope: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="intents")  # noqa: F821
    agent: Mapped["Agent"] = relationship(back_populates="intents")  # noqa: F821
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="intent")  # noqa: F821

    __table_args__ = (
        CheckConstraint(
            "max_amount IS NULL OR min_amount IS NULL OR max_amount >= min_amount",
            name="ck_intents_amount_bounds",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_intents_confidence_range",
        ),
    )

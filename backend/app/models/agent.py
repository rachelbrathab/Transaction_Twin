"""Agent model — an AI agent acting on behalf of a user."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, CompatibleJSONB


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="active"
    )
    trust_score: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    reputation_snapshot: Mapped[dict | None] = mapped_column(CompatibleJSONB(), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", CompatibleJSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="agents")  # noqa: F821
    capabilities: Mapped[list["AgentCapability"]] = relationship(  # noqa: F821
        back_populates="agent", cascade="all, delete-orphan"
    )
    intents: Mapped[list["Intent"]] = relationship(back_populates="agent")  # noqa: F821
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="agent")  # noqa: F821
    transaction_events: Mapped[list["TransactionEvent"]] = relationship(  # noqa: F821
        back_populates="agent"
    )

    __table_args__ = (
        CheckConstraint(
            "trust_score IS NULL OR (trust_score >= 0 AND trust_score <= 1)",
            name="ck_agents_trust_score_range",
        ),
    )

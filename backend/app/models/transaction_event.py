"""Transaction Event model — append-only event history for transaction journeys."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, CompatibleJSONB


class TransactionEvent(Base):
    __tablename__ = "transaction_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict | None] = mapped_column(CompatibleJSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    transaction: Mapped["Transaction"] = relationship(back_populates="events")  # noqa: F821
    agent: Mapped["Agent"] = relationship(back_populates="transaction_events")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("transaction_id", "sequence_number", name="uq_event_transaction_sequence"),
        CheckConstraint("sequence_number > 0", name="ck_events_sequence_positive"),
    )

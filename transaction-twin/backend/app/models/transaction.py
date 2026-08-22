"""Transaction model — the central financial entity."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, CompatibleJSONB


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intents.id", ondelete="CASCADE"), nullable=False
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policies.id", ondelete="SET NULL"), nullable=True
    )
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="proposed")
    payment_provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_provider_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", CompatibleJSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="transactions")  # noqa: F821
    agent: Mapped["Agent"] = relationship(back_populates="transactions")  # noqa: F821
    intent: Mapped["Intent"] = relationship(back_populates="transactions")  # noqa: F821
    policy: Mapped["Policy | None"] = relationship(back_populates="transactions")  # noqa: F821
    merchant: Mapped["Merchant | None"] = relationship(back_populates="transactions")  # noqa: F821
    events: Mapped[list["TransactionEvent"]] = relationship(  # noqa: F821
        back_populates="transaction", cascade="all, delete-orphan"
    )
    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(  # noqa: F821
        back_populates="transaction", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["Decision"]] = relationship(  # noqa: F821
        back_populates="transaction", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("agent_id", "idempotency_key", name="uq_transaction_agent_idempotency"),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
    )

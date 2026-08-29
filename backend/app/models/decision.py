"""Decision model — deterministic decision output for transactions."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, CompatibleJSONB


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    risk_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_assessments.id", ondelete="SET NULL"), nullable=True
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policies.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[dict | None] = mapped_column(CompatibleJSONB(), nullable=True)
    override_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    override_actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # Relationships
    transaction: Mapped["Transaction"] = relationship(back_populates="decisions")  # noqa: F821
    risk_assessment: Mapped["RiskAssessment | None"] = relationship(  # noqa: F821
        back_populates="decisions"
    )
    policy: Mapped["Policy | None"] = relationship(back_populates="decisions")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("transaction_id", "version", name="uq_decision_transaction_version"),
    )

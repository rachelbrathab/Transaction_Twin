"""Risk Assessment model — output from the risk evaluation engine."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, CompatibleJSONB


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    overall_score: Mapped[float | None] = mapped_column(nullable=True)
    intent_match_score: Mapped[float | None] = mapped_column(nullable=True)
    behavioral_risk: Mapped[float | None] = mapped_column(nullable=True)
    agent_trust_score: Mapped[float | None] = mapped_column(nullable=True)
    policy_risk: Mapped[float | None] = mapped_column(nullable=True)
    velocity_risk: Mapped[float | None] = mapped_column(nullable=True)
    merchant_risk: Mapped[float | None] = mapped_column(nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    features: Mapped[dict | None] = mapped_column(CompatibleJSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    transaction: Mapped["Transaction"] = relationship(back_populates="risk_assessments")  # noqa: F821
    decisions: Mapped[list["Decision"]] = relationship(back_populates="risk_assessment")  # noqa: F821

    __table_args__ = (
        CheckConstraint(
            "overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 1)",
            name="ck_risk_overall_score_range",
        ),
        CheckConstraint(
            "intent_match_score IS NULL OR (intent_match_score >= 0 AND intent_match_score <= 1)",
            name="ck_risk_intent_match_score_range",
        ),
        CheckConstraint(
            "behavioral_risk IS NULL OR (behavioral_risk >= 0 AND behavioral_risk <= 1)",
            name="ck_risk_behavioral_risk_range",
        ),
        CheckConstraint(
            "agent_trust_score IS NULL OR (agent_trust_score >= 0 AND agent_trust_score <= 1)",
            name="ck_risk_agent_trust_score_range",
        ),
        CheckConstraint(
            "policy_risk IS NULL OR (policy_risk >= 0 AND policy_risk <= 1)",
            name="ck_risk_policy_risk_range",
        ),
        CheckConstraint(
            "velocity_risk IS NULL OR (velocity_risk >= 0 AND velocity_risk <= 1)",
            name="ck_risk_velocity_risk_range",
        ),
        CheckConstraint(
            "merchant_risk IS NULL OR (merchant_risk >= 0 AND merchant_risk <= 1)",
            name="ck_risk_merchant_risk_range",
        ),
    )

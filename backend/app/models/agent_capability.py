"""Agent Capability model — normalized capabilities for agents."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AgentCapability(Base):
    __tablename__ = "agent_capabilities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # Relationships
    agent: Mapped["Agent"] = relationship(back_populates="capabilities")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("agent_id", "capability", name="uq_agent_capability"),
    )

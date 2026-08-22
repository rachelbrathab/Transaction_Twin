"""Policy model — deterministic constraints on agent behavior."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, CompatibleJSONB


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    rules: Mapped[dict | None] = mapped_column(CompatibleJSONB(), nullable=True)
    scope: Mapped[dict | None] = mapped_column(CompatibleJSONB(), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="policies")  # noqa: F821
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="policy")  # noqa: F821
    decisions: Mapped[list["Decision"]] = relationship(back_populates="policy")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("user_id", "name", "version", name="uq_policy_user_name_version"),
    )

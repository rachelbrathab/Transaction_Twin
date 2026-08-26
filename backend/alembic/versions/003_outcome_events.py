"""add outcome event provenance columns

Revision ID: 003_outcome_events
Revises: 002_core_schema
Create Date: 2026-08-26

Adds provider, external_event_id, source, and verification_state
columns to transaction_events table for Sprint 12 outcome tracking.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_outcome_events"
down_revision: Union[str, None] = "002_core_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable outcome provenance columns to transaction_events
    op.add_column(
        "transaction_events",
        sa.Column("provider", sa.String(100), nullable=True),
    )
    op.add_column(
        "transaction_events",
        sa.Column("external_event_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "transaction_events",
        sa.Column("source", sa.String(50), nullable=True),
    )
    op.add_column(
        "transaction_events",
        sa.Column("verification_state", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transaction_events", "verification_state")
    op.drop_column("transaction_events", "source")
    op.drop_column("transaction_events", "external_event_id")
    op.drop_column("transaction_events", "provider")

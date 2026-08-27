"""add calibration intelligence tables

Revision ID: 004_calibration_intelligence
Revises: 003_outcome_events
Create Date: 2026-08-26

Adds calibration_recommendations and calibration_versions tables
for Sprint 13 verified outcome learning and advisory calibration.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_calibration_intelligence"
down_revision: Union[str, None] = "003_outcome_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── calibration_versions ─────────────────────────────────────
    op.create_table(
        "calibration_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.String(100),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "source_window_days",
            sa.Integer,
            nullable=False,
        ),
        sa.Column(
            "total_samples",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "eligible_samples",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "excluded_samples",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "recommendation_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "parameter_snapshot",
            postgresql.JSONB,
            nullable=True,
        ),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "activated_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "previous_version",
            sa.String(100),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="generated",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_calver_user_id",
        "calibration_versions",
        ["user_id"],
    )
    op.create_index(
        "ix_calver_status",
        "calibration_versions",
        ["status"],
    )

    # ── calibration_recommendations ──────────────────────────────
    op.create_table(
        "calibration_recommendations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recommendation_type",
            sa.String(100),
            nullable=False,
        ),
        sa.Column(
            "engine",
            sa.String(100),
            nullable=False,
        ),
        sa.Column(
            "parameter",
            sa.String(200),
            nullable=True,
        ),
        sa.Column(
            "current_value",
            postgresql.JSONB,
            nullable=True,
        ),
        sa.Column(
            "proposed_value",
            postgresql.JSONB,
            nullable=True,
        ),
        sa.Column(
            "proposed_range",
            postgresql.JSONB,
            nullable=True,
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "sample_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "confidence",
            sa.String(50),
            nullable=False,
            server_default="insufficient",
        ),
        sa.Column(
            "rationale",
            sa.Text,
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.String(50),
            nullable=False,
            server_default="info",
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="generated",
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "activated_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "rejection_reason",
            sa.Text,
            nullable=True,
        ),
        sa.Column(
            "calibration_version",
            sa.String(100),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_calrec_user_id",
        "calibration_recommendations",
        ["user_id"],
    )
    op.create_index(
        "ix_calrec_status",
        "calibration_recommendations",
        ["status"],
    )
    op.create_index(
        "ix_calrec_version",
        "calibration_recommendations",
        ["calibration_version"],
    )
    op.create_index(
        "ix_calrec_engine",
        "calibration_recommendations",
        ["engine"],
    )


def downgrade() -> None:
    op.drop_table("calibration_recommendations")
    op.drop_table("calibration_versions")

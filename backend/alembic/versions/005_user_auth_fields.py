"""add email and password_hash to users for JWT authentication

Revision ID: 005_user_auth_fields
Revises: 004_calibration_intelligence
Create Date: 2026-08-30

Adds email (unique, nullable) and password_hash (nullable) columns to the
users table to support application-level JWT authentication.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_user_auth_fields"
down_revision: Union[str, None] = "004_calibration_intelligence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_users_email",
        "users",
        ["email"],
        unique=True,
        postgresql_where="email IS NOT NULL",
    )
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_hash")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "email")

"""initial foundation — empty schema baseline

Revision ID: 001_initial
Revises:
Create Date: 2025-08-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Initial migration — creates the alembic_version table.

    Business tables will be added in future migrations.
    This establishes the migration chain foundation.
    """
    # Alembic creates the alembic_version table automatically.
    # No additional tables needed for Sprint 1 foundation.
    pass


def downgrade() -> None:
    """Remove foundation tables."""
    pass

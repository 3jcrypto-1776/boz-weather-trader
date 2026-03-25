"""Add timezone display preference to users table.

Allows users to choose a timezone for displaying timestamps
instead of relying on browser default.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add timezone column with empty string default (browser default)."""
    op.add_column("users", sa.Column("timezone", sa.String(), server_default="", nullable=True))


def downgrade() -> None:
    """Remove timezone column."""
    op.drop_column("users", "timezone")

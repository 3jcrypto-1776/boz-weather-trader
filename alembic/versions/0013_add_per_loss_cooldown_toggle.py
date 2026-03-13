"""Add enable_per_loss_cooldown toggle to users table.

Allows users to disable the per-loss cooldown timer independently
of the cooldown duration setting.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add enable_per_loss_cooldown column (default True)."""
    op.add_column(
        "users",
        sa.Column("enable_per_loss_cooldown", sa.Boolean(), server_default=sa.text("true")),
    )


def downgrade() -> None:
    """Remove enable_per_loss_cooldown column."""
    op.drop_column("users", "enable_per_loss_cooldown")

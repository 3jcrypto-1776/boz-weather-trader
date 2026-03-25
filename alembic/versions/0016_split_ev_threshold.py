"""Split min_ev_threshold into separate YES and NO thresholds.

Adds min_ev_threshold_yes (default 0.15) and min_ev_threshold_no (default 0.05)
to the users table. The existing min_ev_threshold column is kept for backward
compatibility. On upgrade, min_ev_threshold_no is set to the existing
min_ev_threshold value to preserve the user's current NO-side setting.

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("min_ev_threshold_yes", sa.Float(), server_default="0.15"),
    )
    op.add_column(
        "users",
        sa.Column("min_ev_threshold_no", sa.Float(), server_default="0.05"),
    )

    # Preserve existing min_ev_threshold value as the NO-side threshold
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE users SET min_ev_threshold_no = min_ev_threshold "
            "WHERE min_ev_threshold IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("users", "min_ev_threshold_no")
    op.drop_column("users", "min_ev_threshold_yes")

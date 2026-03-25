"""Add fee_estimate_mode column to users table.

Adds fee_estimate_mode column with server_default "realistic" so new and
existing users default to the more accurate fee estimation that accounts
for Kalshi's average fee rebate.

Revision ID: 0017
Revises: 0016
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("fee_estimate_mode", sa.String(), server_default="realistic"),
    )


def downgrade() -> None:
    op.drop_column("users", "fee_estimate_mode")

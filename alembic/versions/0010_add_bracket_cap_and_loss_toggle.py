"""Add per-bracket position cap and consecutive loss limit toggle.

Adds two new user settings columns:
- max_contracts_per_bracket: Hard cap on contracts per bracket per market (default 3)
- enable_consecutive_loss_limit: Toggle for rest-of-day cooldown on consecutive losses

Revision ID: 0010
Revises: 0009
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "max_contracts_per_bracket",
            sa.Integer(),
            server_default="3",
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "enable_consecutive_loss_limit",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "enable_consecutive_loss_limit")
    op.drop_column("users", "max_contracts_per_bracket")

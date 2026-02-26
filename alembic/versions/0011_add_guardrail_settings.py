"""Add trading engine guardrail columns.

Adds guardrail settings to the users table and blended_probability to trades:
- model_weight: Weight for model probability in blend (default 0.4)
- max_model_market_divergence: Max divergence from market (default 0.25)
- min_market_prob_for_yes: Floor for YES-side market prob (default 0.15)
- blended_probability: Post-guardrail probability stored on trades

Revision ID: 0011
Revises: 0010
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # User guardrail settings
    op.add_column(
        "users",
        sa.Column(
            "model_weight",
            sa.Float(),
            server_default="0.4",
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "max_model_market_divergence",
            sa.Float(),
            server_default="0.25",
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "min_market_prob_for_yes",
            sa.Float(),
            server_default="0.15",
            nullable=True,
        ),
    )
    # Trade blended probability
    op.add_column(
        "trades",
        sa.Column(
            "blended_probability",
            sa.Float(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("trades", "blended_probability")
    op.drop_column("users", "min_market_prob_for_yes")
    op.drop_column("users", "max_model_market_divergence")
    op.drop_column("users", "model_weight")

"""Floor min_ev_threshold_yes at 0.12 for existing users.

Calibration analysis at v1.9.5 showed the model is systematically
overconfident in the 0.3–0.9 probability range, which makes YES-side
trades disproportionately unprofitable. Raising the YES-side EV
threshold to a 0.12 minimum requires a larger predicted edge before
opening a YES position, which acts as protection until the Phase 2
probability calibration layer (v1.9.6) ships.

This migration only raises users who are below the new floor — anyone
already at or above 0.12 keeps their explicit choice.

Revision ID: 0018
Revises: 0017
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


YES_EV_FLOOR = 0.12


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE users SET min_ev_threshold_yes = :floor "
            "WHERE min_ev_threshold_yes IS NULL OR min_ev_threshold_yes < :floor"
        ),
        {"floor": YES_EV_FLOOR},
    )


def downgrade() -> None:
    # No-op: we don't know the prior per-user values, and lowering thresholds
    # below the floor is something the user can do via the settings UI.
    pass

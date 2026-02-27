"""Add RESTING trade status.

The TradeStatus column uses native_enum=False (stored as VARCHAR), so no
schema alteration is required. This migration exists for audit trail and
to document the new status value.

Revision ID: 0012
Revises: 0011
"""

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # TradeStatus is stored as VARCHAR (native_enum=False) with no CHECK
    # constraint, so RESTING is already a valid value.  Nothing to alter.
    pass


def downgrade() -> None:
    # No schema changes to revert.
    pass

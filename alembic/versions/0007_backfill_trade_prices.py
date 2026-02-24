"""Backfill trade prices from Kalshi reconciliation.

Corrects 6 historical trades whose price_cents, pnl_cents, fees_cents,
or quantity were recorded incorrectly before v1.4.5:
- 5 trades had limit price instead of actual fill price
- 1 trade had quantity=0 instead of fill_count=1

Corrections were derived by comparing app DB records against actual
Kalshi filled order data (taker_fill_cost, fill_count).

For NO-side trades, price_cents is stored as the YES-equivalent:
    price_cents = 100 - (taker_fill_cost // fill_count)

This ensures the settlement formula works correctly:
    NO cost = (100 - price_cents) * quantity

Revision ID: 0007
Revises: 0006
Create Date: 2026-02-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Corrections derived from Kalshi order reconciliation (Feb 24, 2026).
# Each entry: (kalshi_order_id prefix, new_price_cents, new_pnl_cents,
#              new_fees_cents, new_quantity_or_None)
#
# P&L math (matches backend/trading/postmortem.py lines 180-195):
#   WON YES: cost = price * qty, pnl = 100*qty - cost - fees
#   LOST YES: pnl = -price * qty, fees = 0
#   WON NO:  cost = (100-price)*qty, pnl = 100*qty - cost - fees
#   LOST NO: pnl = -(100-price)*qty, fees = 0
#   fees = max(1, int(profit_if_win * 0.15)) * qty
#     YES: profit_if_win = 100 - price
#     NO:  profit_if_win = price  (the YES price)
CORRECTIONS = [
    # AUS B65.5 Feb 23, NO WON. fill_cost=59 → price=100-59=41
    # cost=(100-41)*1=59, fee=max(1,int(41*0.15))*1=6, pnl=100-59-6=35
    ("81f68254", 41, 35, 6, None),
    # NYC T38 Feb 22, YES LOST. fill_cost=18 → price=18
    # pnl=-18*1=-18, fees=0
    ("ce603eed", 18, -18, 0, None),
    # CHI B35.5 Feb 21, NO WON. fill_cost=63 → price=100-63=37
    # cost=(100-37)*1=63, fee=max(1,int(37*0.15))*1=5, pnl=100-63-5=32
    ("40a06d74", 37, 32, 5, None),
    # AUS B73.5 Feb 21, NO WON. fill_cost=66 → price=100-66=34
    # cost=(100-34)*1=66, fee=max(1,int(34*0.15))*1=5, pnl=100-66-5=29
    ("86d614d9", 34, 29, 5, None),
    # AUS B73.5 Feb 21, NO WON (second order). Same math as above.
    ("a614e02a", 34, 29, 5, None),
    # MIA B83.5 Feb 21, NO LOST. qty 0→1, price=65
    # cost=(100-65)*1=35, pnl=-35, fees=0
    ("9d216e34", 65, -35, 0, 1),
]


def upgrade() -> None:
    """Backfill corrected prices, P&L, fees, and quantity for 6 trades."""
    conn = op.get_bind()

    for oid_prefix, new_price, new_pnl, new_fees, new_qty in CORRECTIONS:
        # Build the update dynamically based on whether quantity needs fixing
        if new_qty is not None:
            conn.execute(
                sa.text(
                    "UPDATE trades "
                    "SET price_cents = :price, pnl_cents = :pnl, "
                    "    fees_cents = :fees, quantity = :qty "
                    "WHERE kalshi_order_id LIKE :oid_pattern"
                ),
                {
                    "price": new_price,
                    "pnl": new_pnl,
                    "fees": new_fees,
                    "qty": new_qty,
                    "oid_pattern": f"{oid_prefix}%",
                },
            )
        else:
            conn.execute(
                sa.text(
                    "UPDATE trades "
                    "SET price_cents = :price, pnl_cents = :pnl, "
                    "    fees_cents = :fees "
                    "WHERE kalshi_order_id LIKE :oid_pattern"
                ),
                {
                    "price": new_price,
                    "pnl": new_pnl,
                    "fees": new_fees,
                    "oid_pattern": f"{oid_prefix}%",
                },
            )


def downgrade() -> None:
    """Revert is not supported for data backfill migrations.

    The original incorrect values are not preserved. If needed,
    the trades can be re-synced from Kalshi via the sync endpoint.
    """
    pass

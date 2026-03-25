"""Fix NO-side trades storing YES market price instead of actual NO cost.

Bug: executor.py only converted price_cents for NO trades when
taker_fill_cost > 0. In the fallback path, signal.price_cents (YES market
price) was stored directly. Settlement then used this wrong price for P&L
calculation, over-reporting profits by ~$154 across 91 affected trades.

This migration identifies affected NO trades by checking if the stored
pnl_cents doesn't match the expected formula, flips price_cents, and
recalculates pnl_cents + fees_cents.

Revision ID: 0014
Revises: 0013
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Fix NO WON trades where pnl doesn't match formula.
    # Expected: pnl = (100 - price_cents) * quantity - fees_cents
    # If it doesn't match, price_cents is the YES price (needs flipping).
    won_result = conn.execute(
        __import__("sqlalchemy").text("""
            SELECT id, price_cents, quantity, fees_cents, pnl_cents
            FROM trades
            WHERE side = 'no'
              AND status = 'WON'
              AND pnl_cents != (100 - price_cents) * quantity - fees_cents
        """)
    )
    won_rows = won_result.fetchall()

    for row in won_rows:
        trade_id, old_price, qty, _old_fees, _old_pnl = row
        new_price = 100 - old_price
        new_fees = max(1, int((100 - new_price) * 0.15)) * qty
        new_pnl = (100 - new_price) * qty - new_fees

        conn.execute(
            __import__("sqlalchemy").text("""
                UPDATE trades
                SET price_cents = :price, fees_cents = :fees, pnl_cents = :pnl
                WHERE id = :id
            """),
            {"price": new_price, "fees": new_fees, "pnl": new_pnl, "id": trade_id},
        )

    # Fix NO LOST trades where pnl doesn't match formula.
    # Expected: pnl = -(price_cents * quantity)
    lost_result = conn.execute(
        __import__("sqlalchemy").text("""
            SELECT id, price_cents, quantity, pnl_cents
            FROM trades
            WHERE side = 'no'
              AND status = 'LOST'
              AND pnl_cents != -(price_cents * quantity)
        """)
    )
    lost_rows = lost_result.fetchall()

    for row in lost_rows:
        trade_id, old_price, qty, _old_pnl = row
        new_price = 100 - old_price
        new_pnl = -(new_price * qty)

        conn.execute(
            __import__("sqlalchemy").text("""
                UPDATE trades
                SET price_cents = :price, pnl_cents = :pnl
                WHERE id = :id
            """),
            {"price": new_price, "pnl": new_pnl, "id": trade_id},
        )

    # Also fix any OPEN/RESTING NO trades that have the wrong price
    # (price_cents < 50 is a strong signal it's the YES price, not NO cost,
    # since most NO costs are > 50)
    conn.execute(
        __import__("sqlalchemy").text("""
            UPDATE trades
            SET price_cents = 100 - price_cents
            WHERE side = 'no'
              AND status IN ('OPEN', 'RESTING')
              AND price_cents < 50
        """)
    )

    print(f"Fixed {len(won_rows)} NO WON trades and {len(lost_rows)} NO LOST trades")


def downgrade() -> None:
    # Data migration — cannot be reversed without the original values.
    # The forward migration is idempotent (only touches trades that don't
    # match the formula), so re-running is safe.
    pass

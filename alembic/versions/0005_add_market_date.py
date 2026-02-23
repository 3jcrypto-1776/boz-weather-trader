"""Add market_date column to trades table.

The market_date column stores the actual market event date extracted from the
Kalshi ticker (e.g., KXHIGHAUS-26FEB23 → 2026-02-23). Previously, settlement
matching used trade_date (order placement time), which caused trades placed in
the evening to be settled against the wrong day's data.

Includes a Python-based backfill that parses the date from each trade's
market_ticker field.

Revision ID: 0005
Revises: 0004
Create Date: 2026-02-23
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _parse_date_from_ticker(ticker: str) -> datetime | None:
    """Parse market event date from a Kalshi ticker string.

    Duplicated here (instead of importing from backend) because migrations
    must be self-contained and not depend on application code that may change.

    Args:
        ticker: Market ticker like "KXHIGHAUS-26FEB23-T63".

    Returns:
        Date as datetime (midnight), or None if parsing fails.
    """
    parts = ticker.split("-")
    if len(parts) < 2:
        return None

    date_str = parts[1].upper()
    try:
        return datetime.strptime(date_str, "%y%b%d")
    except ValueError:
        return None


def upgrade() -> None:
    """Add market_date column and backfill from market_ticker."""
    # 1. Add nullable column
    op.add_column(
        "trades",
        sa.Column("market_date", sa.DateTime(), nullable=True),
    )

    # 2. Backfill existing trades from their market_ticker
    conn = op.get_bind()
    trades = conn.execute(
        sa.text("SELECT id, market_ticker FROM trades WHERE market_date IS NULL")
    )

    for row in trades:
        trade_id = row[0]
        ticker = row[1]
        parsed = _parse_date_from_ticker(ticker)
        if parsed is not None:
            conn.execute(
                sa.text("UPDATE trades SET market_date = :md WHERE id = :tid"),
                {"md": parsed, "tid": trade_id},
            )


def downgrade() -> None:
    """Remove market_date column."""
    op.drop_column("trades", "market_date")

"""Update bracket_label format to match Kalshi display.

Changes bracket labels in trades and pending_trades tables:
- "Below XF" → "(X-1)°F or below"  (e.g., "Below 73F" → "72°F or below")
- "X-YF" → "X° to (Y-1)°F"  (e.g., "52-54F" → "52° to 53°F")
- "XF or above" → "X°F or above"  (e.g., "58F or above" → "58°F or above")

Uses Python-based backfill to handle the arithmetic (subtract 1 from upper bound).

Revision ID: 0006
Revises: 0005
Create Date: 2026-02-23
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _convert_label(old_label: str) -> str | None:
    """Convert an old-format bracket label to the new Kalshi-matching format.

    Returns the new label, or None if no conversion needed.
    """
    # Bottom edge: "Below 73F" → "72°F or below"
    m = re.match(r"^Below (\d+)F$", old_label)
    if m:
        temp = int(m.group(1)) - 1
        return f"{temp}°F or below"

    # Middle: "52-54F" → "52° to 53°F"
    m = re.match(r"^(\d+)-(\d+)F$", old_label)
    if m:
        low = int(m.group(1))
        high = int(m.group(2)) - 1
        return f"{low}° to {high}°F"

    # Top edge: "58F or above" → "58°F or above"
    m = re.match(r"^(\d+)F or above$", old_label)
    if m:
        temp = int(m.group(1))
        return f"{temp}°F or above"

    return None


def _update_table(table_name: str) -> int:
    """Update bracket labels in the given table. Returns count of rows updated."""
    conn = op.get_bind()

    # Fetch all rows with old-format labels
    rows = conn.execute(
        sa.text(
            f"SELECT id, bracket_label FROM {table_name} "  # noqa: S608
            "WHERE bracket_label LIKE 'Below %F' "
            "OR bracket_label ~ '^[0-9]+-[0-9]+F$' "
            "OR bracket_label ~ '^[0-9]+F or above$'"
        )
    ).fetchall()

    updated = 0
    for row in rows:
        row_id, old_label = row[0], row[1]
        new_label = _convert_label(old_label)
        if new_label and new_label != old_label:
            conn.execute(
                sa.text(
                    f"UPDATE {table_name} SET bracket_label = :new_label "  # noqa: S608
                    "WHERE id = :id"
                ),
                {"new_label": new_label, "id": row_id},
            )
            updated += 1

    return updated


def upgrade() -> None:
    """Update bracket labels to match Kalshi display format."""
    trades_updated = _update_table("trades")
    pending_updated = _update_table("pending_trades")

    if trades_updated or pending_updated:
        print(
            f"  Updated bracket labels: {trades_updated} trades, "
            f"{pending_updated} pending trades"
        )


def downgrade() -> None:
    """Revert bracket labels to old format (best-effort)."""
    conn = op.get_bind()

    # Revert "X°F or below" → "Below (X+1)F"
    rows = conn.execute(
        sa.text(
            "SELECT id, bracket_label FROM trades "
            "WHERE bracket_label LIKE '%°F or below'"
        )
    ).fetchall()
    for row in rows:
        m = re.match(r"^(\d+)°F or below$", row[1])
        if m:
            temp = int(m.group(1)) + 1
            conn.execute(
                sa.text("UPDATE trades SET bracket_label = :label WHERE id = :id"),
                {"label": f"Below {temp}F", "id": row[0]},
            )

    # Revert "X° to Y°F" → "X-(Y+1)F"
    rows = conn.execute(
        sa.text(
            "SELECT id, bracket_label FROM trades "
            "WHERE bracket_label LIKE '%° to %°F'"
        )
    ).fetchall()
    for row in rows:
        m = re.match(r"^(\d+)° to (\d+)°F$", row[1])
        if m:
            low = int(m.group(1))
            high = int(m.group(2)) + 1
            conn.execute(
                sa.text("UPDATE trades SET bracket_label = :label WHERE id = :id"),
                {"label": f"{low}-{high}F", "id": row[0]},
            )

    # Revert "X°F or above" → "XF or above"
    rows = conn.execute(
        sa.text(
            "SELECT id, bracket_label FROM trades "
            "WHERE bracket_label LIKE '%°F or above'"
        )
    ).fetchall()
    for row in rows:
        m = re.match(r"^(\d+)°F or above$", row[1])
        if m:
            conn.execute(
                sa.text("UPDATE trades SET bracket_label = :label WHERE id = :id"),
                {"label": f"{m.group(1)}F or above", "id": row[0]},
            )

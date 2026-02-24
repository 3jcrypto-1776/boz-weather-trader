"""Fix bracket labels affected by integer cap_strike off-by-one bug.

When Kalshi returns integer cap_strike values (e.g., 73.0 instead of 72.99),
the old code used int(cap) which produced "73°F or below" instead of the
correct "72°F or below". The code fix uses math.ceil(cap) - 1 to handle
both formats consistently.

This migration fixes existing trades and predictions with wrong labels:
- Bottom brackets: "{N}°F or below" → "{N-1}°F or below" where N matches ticker
- Middle brackets: "{X}° to {N}°F" → "{X}° to {N-1}°F" where N is off by one

Strategy: Parse the market_ticker's T{threshold} suffix to derive the correct
label. For bottom bracket T73: correct label = "72°F or below" (threshold - 1).
For middle bracket with floor=52 and threshold as cap's next int: ceil(cap)-1.

Revision ID: 0008
Revises: 0007
Create Date: 2026-02-24
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fix_bracket_label(label: str, cap_strike: float | None) -> str | None:
    """Recalculate a bracket label using the fixed math.ceil(cap) - 1 formula.

    Returns the corrected label, or None if no fix needed.
    """
    if cap_strike is None:
        return None

    # Bottom edge: "{N}°F or below"
    m = re.match(r"^(\d+)°F or below$", label)
    if m:
        old_val = int(m.group(1))
        correct_val = math.ceil(cap_strike) - 1
        if old_val != correct_val:
            return f"{correct_val}°F or below"
        return None

    # Middle: "{X}° to {Y}°F"
    m = re.match(r"^(\d+)° to (\d+)°F$", label)
    if m:
        floor_val = int(m.group(1))
        old_cap_val = int(m.group(2))
        correct_cap_val = math.ceil(cap_strike) - 1
        if old_cap_val != correct_cap_val:
            return f"{floor_val}° to {correct_cap_val}°F"
        return None

    return None


def upgrade() -> None:
    """Fix bracket labels on trades and predictions affected by integer cap_strike."""
    conn = op.get_bind()

    # ─── Fix trades table ───
    # Find all trades with bottom bracket labels and check if they're off by one.
    # We can detect wrong labels by looking at the market_ticker:
    #   Ticker "KXHIGHAUS-26FEB24-T73" → T73 → for bottom bracket, correct = "72°F or below"
    #   If trade has "73°F or below", it's wrong (off by one).
    trades = conn.execute(
        sa.text(
            "SELECT id, bracket_label, market_ticker "
            "FROM trades "
            "WHERE bracket_label LIKE '%°F or below' "
            "AND market_ticker IS NOT NULL"
        )
    ).fetchall()

    fixed_trades = 0
    for trade_id, label, ticker in trades:
        # Extract T{N} from ticker like "KXHIGHAUS-26FEB24-T73"
        parts = ticker.split("-")
        if len(parts) < 3:
            continue
        bracket_part = parts[-1]  # e.g., "T73"
        if not bracket_part.startswith("T"):
            continue
        try:
            threshold = int(bracket_part[1:])
        except ValueError:
            continue

        # For bottom bracket: correct label = "{threshold - 1}°F or below"
        correct_label = f"{threshold - 1}°F or below"
        if label != correct_label:
            conn.execute(
                sa.text("UPDATE trades SET bracket_label = :new_label WHERE id = :tid"),
                {"new_label": correct_label, "tid": trade_id},
            )
            fixed_trades += 1

    # Also fix middle brackets with off-by-one cap values.
    # For middle brackets, we can't easily derive the correct cap from the ticker alone
    # because the ticker suffix is the floor value. But we know the pattern:
    # if a middle bracket label says "X° to {N}°F" and N is one too high compared
    # to what ceil(cap_strike)-1 should be, we need the actual cap_strike.
    # Since we don't store cap_strike in trades, we skip middle bracket fixes here.
    # The code fix prevents this going forward.

    # ─── Fix predictions table (brackets_json) ───
    # The brackets_json stores bracket labels that are used by the trading cycle.
    # If a prediction has wrong labels, future trading cycles would still produce
    # wrong-labeled trades. Fix them so the next cycle reads correct labels.
    #
    # We fix bottom bracket labels by recalculating from upper_bound_f in the JSON.
    import json

    predictions = conn.execute(
        sa.text(
            "SELECT id, brackets_json FROM predictions WHERE brackets_json IS NOT NULL"
        )
    ).fetchall()

    fixed_predictions = 0
    for pred_id, brackets_raw in predictions:
        if isinstance(brackets_raw, str):
            brackets = json.loads(brackets_raw)
        else:
            brackets = brackets_raw

        if not isinstance(brackets, list):
            continue

        changed = False
        for bracket in brackets:
            label = bracket.get("bracket_label", "")
            upper = bracket.get("upper_bound_f")
            lower = bracket.get("lower_bound_f")

            if upper is not None:
                # Bottom edge: lower_bound_f is None
                if lower is None:
                    new_label = _fix_bracket_label(label, upper)
                    if new_label:
                        bracket["bracket_label"] = new_label
                        changed = True
                # Middle bracket
                elif lower is not None:
                    new_label = _fix_bracket_label(label, upper)
                    if new_label:
                        bracket["bracket_label"] = new_label
                        changed = True

        if changed:
            conn.execute(
                sa.text("UPDATE predictions SET brackets_json = :bj WHERE id = :pid"),
                {"bj": json.dumps(brackets), "pid": pred_id},
            )
            fixed_predictions += 1

    print(f"Fixed {fixed_trades} trade(s) and {fixed_predictions} prediction(s)")


def downgrade() -> None:
    """No downgrade — this is a data correction, not reversible."""
    pass

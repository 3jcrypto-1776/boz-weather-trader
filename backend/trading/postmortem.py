"""Post-settlement trade analysis and narrative generation.

Two settlement paths:

1. **Kalshi-based (primary):** settle_from_kalshi() uses Kalshi's authoritative
   market_result ("yes"/"no") to determine win/loss. NWS temperature data is
   optional and used only for display (settlement_temp_f, post-mortem narratives).

2. **NWS-based (legacy):** settle_trade() determines win/loss from NWS CLI
   temperature data via _did_bracket_win(). Used by backtesting and as fallback.

CRITICAL: All monetary calculations use CENTS (integers). The Trade ORM model
uses pnl_cents (int) and fees_cents (int).

Usage:
    from backend.trading.postmortem import settle_from_kalshi

    await settle_from_kalshi(trade, market_result="yes", db=db, nws_settlement=s)
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.logging import get_logger
from backend.common.models import (
    Settlement,
    Trade,
    TradeStatus,
    WeatherForecast,
)
from backend.weather.stations import STATION_CONFIGS

logger = get_logger("POSTMORTEM")

# City display names for narratives
_CITY_NAMES: dict[str, str] = {
    "NYC": "New York",
    "CHI": "Chicago",
    "MIA": "Miami",
    "AUS": "Austin",
}


def generate_postmortem_narrative(
    trade: Trade,
    settlement: Settlement,
    forecasts: list[WeatherForecast],
) -> str:
    """Generate a structured post-mortem executive summary for a trade.

    Produces a multi-section narrative covering what was traded, what
    happened, why the trade was taken, forecast accuracy, and economics.

    Args:
        trade: The Trade ORM model (must have status set to WON or LOST).
        settlement: The Settlement ORM with actual temperature data.
        forecasts: Weather forecasts that were active at trade time.

    Returns:
        A multi-line narrative string with section headers.
    """
    city_code = trade.city.value if hasattr(trade.city, "value") else trade.city
    city_name = _CITY_NAMES.get(city_code, city_code)
    actual_temp = settlement.actual_high_f
    bracket = trade.bracket_label
    side = trade.side.upper()
    price_cents = trade.price_cents
    quantity = trade.quantity
    pnl_cents = trade.pnl_cents or 0
    fees_cents = trade.fees_cents or 0
    model_prob = trade.model_probability
    market_prob = trade.market_probability
    ev_at_entry = trade.ev_at_entry
    confidence = trade.confidence

    # Station name from config
    station_cfg = STATION_CONFIGS.get(city_code)
    station_name = station_cfg.station_name if station_cfg else city_code

    # Trade date formatting
    trade_dt = trade.trade_date
    date_str = trade_dt.strftime("%b %d, %Y") if hasattr(trade_dt, "strftime") else str(trade_dt)

    # Result line
    is_win = trade.status == TradeStatus.WON
    result_emoji = "WIN" if is_win else "LOSS"
    pnl_str = f"+${pnl_cents / 100:.2f}" if pnl_cents >= 0 else f"-${abs(pnl_cents) / 100:.2f}"

    # Edge calculation
    edge_pp = round((model_prob - market_prob) * 100)

    # Bracket hit check
    bracket_hit = _did_bracket_win(bracket, actual_temp, "yes")
    bracket_status = "hit" if bracket_hit else "miss"

    lines: list[str] = []

    # Header
    trade_id_short = trade.id[:8] if trade.id else "?"
    lines.append(f"TRADE #{trade_id_short} -- {city_name} High Temp | {date_str}")
    lines.append(f"Result: {result_emoji}  |  P&L: {pnl_str}")
    lines.append("")

    # WHAT WE TRADED
    lines.append("WHAT WE TRADED")
    contract_word = "contract" if quantity == 1 else "contracts"
    lines.append(
        f"  Bought {side} on {bracket} bracket"
        f" @ ${price_cents / 100:.2f} ({quantity} {contract_word})"
    )
    lines.append("")

    # WHAT HAPPENED
    lines.append("WHAT HAPPENED")
    lines.append(f"  Actual high: {actual_temp:.0f}F ({settlement.source}, {station_name})")
    lines.append(f"  Bracket {bracket}: {bracket_status}")
    lines.append("")

    # WHY WE TOOK THIS TRADE
    lines.append("WHY WE TOOK THIS TRADE")
    lines.append(f"  Model predicted {model_prob:.0%} chance for this bracket")
    lines.append(
        f"  Market priced at {market_prob:.0%} (${price_cents / 100:.2f}) -- {edge_pp} pp edge"
    )
    lines.append(f"  Confidence: {confidence.upper()}")
    lines.append("")

    # FORECAST ACCURACY
    if forecasts:
        lines.append("FORECAST ACCURACY")
        sorted_fc = sorted(
            forecasts,
            key=lambda f: abs(f.forecast_high_f - actual_temp),
        )
        for fc in sorted_fc[:4]:
            diff = fc.forecast_high_f - actual_temp
            sign = "+" if diff >= 0 else ""
            lines.append(f"  {fc.source}: {fc.forecast_high_f:.0f}F ({sign}{diff:.0f}F off)")
        lines.append("")

    # TRADE ECONOMICS
    lines.append("TRADE ECONOMICS")
    lines.append(f"  EV at entry: {ev_at_entry * 100:+.1f}% per contract")
    if fees_cents > 0:
        lines.append(f"  Fees: ${fees_cents / 100:.2f}  |  Net P&L: {pnl_str}")
    else:
        lines.append(f"  Net P&L: {pnl_str}")

    return "\n".join(lines)


async def settle_trade(
    trade: Trade,
    settlement: Settlement,
    db: AsyncSession,
) -> None:
    """Settle a trade after the actual temperature is known.

    Determines win/loss, calculates P&L (including fees in cents),
    generates a post-mortem narrative, and updates the trade record.

    Args:
        trade: The Trade ORM record to settle (must be OPEN status).
        settlement: The Settlement ORM with actual temperature data.
        db: Async database session.
    """
    actual_temp = settlement.actual_high_f

    # Determine if the bracket was hit
    won = _did_bracket_win(trade.bracket_label, actual_temp, trade.side)

    # Calculate P&L in cents.
    # price_cents = actual cost per contract for both YES and NO sides.
    cost_cents = trade.price_cents * trade.quantity

    if won:
        payout_cents = 100 * trade.quantity
        profit_cents = payout_cents - cost_cents
        # Kalshi fee: ceil(0.07 * C * P * (1-P)), P = YES price in dollars
        yes_price = trade.price_cents if trade.side == "yes" else (100 - trade.price_cents)
        p = yes_price / 100
        fee_per_contract = max(1, math.ceil(7 * p * (1 - p)))
        fee_cents = fee_per_contract * trade.quantity
        pnl_cents = profit_cents - fee_cents
        trade.status = TradeStatus.WON
        trade.fees_cents = fee_cents
    else:
        pnl_cents = -cost_cents
        trade.status = TradeStatus.LOST
        trade.fees_cents = 0

    trade.pnl_cents = pnl_cents
    trade.settlement_temp_f = actual_temp
    trade.settlement_source = settlement.source
    trade.settled_at = datetime.now(UTC).replace(tzinfo=None)

    # Fetch forecasts for the post-mortem narrative.
    # Use market_date (the event date) to find relevant forecasts, not trade_date
    # (which is order placement time and may be the evening before).
    forecast_date = trade.market_date if trade.market_date is not None else trade.trade_date
    forecasts_result = await db.execute(
        select(WeatherForecast).where(
            WeatherForecast.city == trade.city,
            WeatherForecast.forecast_date == forecast_date,
        )
    )
    forecasts = list(forecasts_result.scalars().all())

    # Generate and store the narrative
    trade.postmortem_narrative = generate_postmortem_narrative(trade, settlement, forecasts)

    await db.flush()

    logger.info(
        "Trade settled",
        extra={
            "data": {
                "trade_id": trade.id,
                "status": trade.status.value,
                "pnl_cents": trade.pnl_cents,
                "fees_cents": trade.fees_cents,
                "actual_temp_f": actual_temp,
                "bracket": trade.bracket_label,
            }
        },
    )


async def settle_from_kalshi(
    trade: Trade,
    market_result: str,
    db: AsyncSession,
    nws_settlement: Settlement | None = None,
) -> None:
    """Settle a trade using Kalshi's authoritative market result.

    Uses Kalshi's market_result ("yes"/"no") to determine win/loss instead
    of parsing bracket labels against NWS temperature data. This eliminates
    bracket-parsing bugs and premature settlement issues.

    P&L is calculated locally using the same math as settle_trade(), since
    Kalshi's revenue field is per-ticker (entire position) rather than
    per-order.

    NWS settlement data is optional and used only for display fields
    (settlement_temp_f) and post-mortem narrative generation.

    Args:
        trade: The Trade ORM record to settle (must be OPEN status).
        market_result: Kalshi's market outcome — "yes" or "no".
        db: Async database session.
        nws_settlement: Optional NWS Settlement for temp display/narratives.
    """
    won = market_result == trade.side

    # P&L calculation — price_cents = actual cost per contract for both sides.
    cost_cents = trade.price_cents * trade.quantity

    if won:
        payout_cents = 100 * trade.quantity
        profit_cents = payout_cents - cost_cents
        # Kalshi fee: ceil(0.07 * C * P * (1-P)), P = YES price in dollars
        yes_price = trade.price_cents if trade.side == "yes" else (100 - trade.price_cents)
        p = yes_price / 100
        fee_per_contract = max(1, math.ceil(7 * p * (1 - p)))
        fee_cents = fee_per_contract * trade.quantity
        pnl_cents = profit_cents - fee_cents
        trade.status = TradeStatus.WON
        trade.fees_cents = fee_cents
    else:
        pnl_cents = -cost_cents
        trade.status = TradeStatus.LOST
        trade.fees_cents = 0

    trade.pnl_cents = pnl_cents
    trade.settlement_source = "KALSHI"
    trade.settled_at = datetime.now(UTC).replace(tzinfo=None)

    # Fill display-only temperature from NWS if available
    if nws_settlement is not None:
        trade.settlement_temp_f = nws_settlement.actual_high_f

        # Generate post-mortem narrative (requires NWS data for temp/forecasts)
        forecast_date = trade.market_date if trade.market_date is not None else trade.trade_date
        forecasts_result = await db.execute(
            select(WeatherForecast).where(
                WeatherForecast.city == trade.city,
                WeatherForecast.forecast_date == forecast_date,
            )
        )
        forecasts = list(forecasts_result.scalars().all())
        trade.postmortem_narrative = generate_postmortem_narrative(trade, nws_settlement, forecasts)

    await db.flush()

    logger.info(
        "Trade settled via Kalshi",
        extra={
            "data": {
                "trade_id": trade.id,
                "ticker": trade.market_ticker,
                "market_result": market_result,
                "side": trade.side,
                "status": trade.status.value,
                "pnl_cents": trade.pnl_cents,
            }
        },
    )


def _did_bracket_win(
    bracket_label: str,
    actual_temp: float,
    side: str,
) -> bool:
    """Determine if a bracket/side combination won given the actual temperature.

    Supported bracket label formats:
        "53-54F"   -> standard bracket: lower <= temp <= upper
        "<=52F"    -> bottom catch-all: temp <= bound
        ">=57F"    -> top catch-all: temp >= bound

    Also supports degree symbol variants: "53-54\u00b0F", "<=52\u00b0F"

    Args:
        bracket_label: The bracket label string.
        actual_temp: The actual high temperature in Fahrenheit.
        side: The trade side ("yes" or "no").

    Returns:
        True if the trade won, False if it lost.
    """
    # Normalize: strip degree symbols and whitespace
    label = bracket_label.replace("\u00b0", "").replace(" ", "").strip()
    bracket_hit = False

    if label.startswith("<=") or label.lower().endswith("below"):
        # Bottom catch-all bracket
        match = re.search(r"[\d.]+", label)
        if match:
            upper = float(match.group())
            bracket_hit = actual_temp <= upper
    elif label.startswith(">=") or label.lower().endswith("above"):
        # Top catch-all bracket
        match = re.search(r"[\d.]+", label)
        if match:
            lower = float(match.group())
            bracket_hit = actual_temp >= lower
    else:
        # Standard bracket: "53-54F" or "53-54"
        # Remove trailing F if present
        clean = label.rstrip("Ff")
        parts = clean.split("-")
        if len(parts) != 2 and "to" in clean.lower():
            parts = clean.lower().split("to")
        if len(parts) == 2:
            try:
                lower = float(parts[0])
                upper = float(parts[1])
                bracket_hit = lower <= actual_temp <= upper
            except ValueError:
                logger.error(
                    "Failed to parse bracket label",
                    extra={"data": {"bracket_label": bracket_label}},
                )
                return False

    if side == "yes":
        return bracket_hit
    else:  # "no"
        return not bracket_hit

"""Calendar endpoint — monthly aggregated trading data for the calendar view.

Returns daily P&L, trade counts, win rates, weekly summaries, and monthly
totals. All aggregation is pushed to SQL for efficiency.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.response_schemas import (
    CalendarDay,
    CalendarMonth,
    CalendarWeek,
)
from backend.common.database import get_db
from backend.common.logging import get_logger
from backend.common.models import Trade, TradeStatus, User

logger = get_logger("API")

router = APIRouter()

_SETTLED_STATUSES = [TradeStatus.WON, TradeStatus.LOST]


@router.get("", response_model=CalendarMonth)
async def get_calendar(
    year: int = Query(..., ge=2024, le=2030),
    month: int = Query(..., ge=1, le=12),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalendarMonth:
    """Fetch aggregated daily trading stats for a calendar month.

    Uses SQL aggregation grouped by trade_date to produce daily P&L,
    trade counts, and win rates. Weekly summaries are computed in
    Python from the daily rows.

    Args:
        year: Calendar year (2024-2030).
        month: Calendar month (1-12).
        user: The authenticated user.
        db: Async database session.

    Returns:
        CalendarMonth with daily stats, weekly summaries, and totals.
    """
    daily_result = await db.execute(
        select(
            func.date(Trade.trade_date).label("tdate"),
            func.count().label("trade_count"),
            func.sum(case((Trade.status == TradeStatus.WON, 1), else_=0)).label("wins"),
            func.sum(case((Trade.status == TradeStatus.LOST, 1), else_=0)).label("losses"),
            func.coalesce(func.sum(Trade.pnl_cents), 0).label("pnl_cents"),
        )
        .where(
            Trade.user_id == user.id,
            Trade.status.in_(_SETTLED_STATUSES),
            extract("year", Trade.trade_date) == year,
            extract("month", Trade.trade_date) == month,
        )
        .group_by(func.date(Trade.trade_date))
        .order_by(func.date(Trade.trade_date).asc())
    )

    daily_rows = daily_result.all()

    # Build daily stats
    days: list[CalendarDay] = []
    total_pnl = 0
    total_trades = 0
    total_wins = 0
    total_losses = 0

    # Group by ISO week for weekly summaries
    week_data: dict[int, dict] = defaultdict(
        lambda: {"pnl_cents": 0, "trade_count": 0, "trading_days": 0}
    )

    for row in daily_rows:
        trade_count = row.trade_count
        wins = row.wins
        losses = row.losses
        pnl = row.pnl_cents
        win_rate = wins / trade_count if trade_count > 0 else 0.0
        date_str = str(row.tdate)

        days.append(
            CalendarDay(
                date=date_str,
                trade_count=trade_count,
                wins=wins,
                losses=losses,
                pnl_cents=pnl,
                win_rate=round(win_rate, 4),
            )
        )

        total_pnl += pnl
        total_trades += trade_count
        total_wins += wins
        total_losses += losses

        # Parse date for ISO week number
        d = date.fromisoformat(date_str)
        iso_week = d.isocalendar()[1]
        week_data[iso_week]["pnl_cents"] += pnl
        week_data[iso_week]["trade_count"] += trade_count
        week_data[iso_week]["trading_days"] += 1

    # Build weekly summaries sorted by week number
    weeks = [
        CalendarWeek(
            week_number=wk,
            pnl_cents=data["pnl_cents"],
            trade_count=data["trade_count"],
            trading_days=data["trading_days"],
        )
        for wk, data in sorted(week_data.items())
    ]

    trading_days = len(days)

    logger.info(
        "Calendar data fetched",
        extra={
            "data": {
                "year": year,
                "month": month,
                "trading_days": trading_days,
                "total_trades": total_trades,
            }
        },
    )

    return CalendarMonth(
        year=year,
        month=month,
        days=days,
        weeks=weeks,
        total_pnl_cents=total_pnl,
        total_trades=total_trades,
        total_wins=total_wins,
        total_losses=total_losses,
        trading_days=trading_days,
    )

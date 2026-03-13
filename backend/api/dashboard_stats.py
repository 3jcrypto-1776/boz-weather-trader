"""Dashboard stats endpoint — P&L and W/L across multiple time periods.

Returns aggregated P&L and win/loss counts for yesterday, week (7 days),
month (30 days), year (365 days), and all-time. Used by the dashboard
P&L toggle and W/L record cards.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, user_to_settings
from backend.api.response_schemas import CooldownStatus, DashboardStats, PeriodStats
from backend.common.database import get_db
from backend.common.logging import get_logger
from backend.common.models import DailyRiskState, Trade, TradeStatus, User

logger = get_logger("API")

ET = ZoneInfo("America/New_York")

router = APIRouter()

_SETTLED_STATUSES = [TradeStatus.WON, TradeStatus.LOST]


async def _query_period(db: AsyncSession, user_id: str, since_date: datetime | None) -> PeriodStats:
    """Query P&L and W/L stats for trades on or after a given date.

    Args:
        db: Async database session.
        user_id: The user's ID.
        since_date: Minimum trade_date (inclusive), or None for all-time.

    Returns:
        PeriodStats with pnl_cents, wins, and losses.
    """
    query = select(
        func.coalesce(func.sum(Trade.pnl_cents), 0).label("pnl"),
        func.coalesce(func.sum(case((Trade.status == TradeStatus.WON, 1), else_=0)), 0).label(
            "wins"
        ),
        func.coalesce(func.sum(case((Trade.status == TradeStatus.LOST, 1), else_=0)), 0).label(
            "losses"
        ),
    ).where(
        Trade.user_id == user_id,
        Trade.status.in_(_SETTLED_STATUSES),
    )

    if since_date is not None:
        query = query.where(func.date(Trade.trade_date) >= since_date)

    result = await db.execute(query)
    row = result.one()
    return PeriodStats(pnl_cents=int(row.pnl), wins=int(row.wins), losses=int(row.losses))


@router.get("", response_model=DashboardStats)
async def get_dashboard_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardStats:
    """Fetch P&L and W/L stats for 5 time periods.

    Periods are computed in ET timezone:
    - yesterday: trades from yesterday only
    - week: last 7 days (including today)
    - month: last 30 days
    - year: last 365 days
    - all_time: all settled trades

    Args:
        user: The authenticated user.
        db: Async database session.

    Returns:
        DashboardStats with PeriodStats for each time window.
    """
    today_et = datetime.now(ET).date()
    yesterday_et = today_et - timedelta(days=1)
    week_start = today_et - timedelta(days=6)
    month_start = today_et - timedelta(days=29)
    year_start = today_et - timedelta(days=364)

    # Query yesterday as a single-day range
    yesterday_query = select(
        func.coalesce(func.sum(Trade.pnl_cents), 0).label("pnl"),
        func.coalesce(func.sum(case((Trade.status == TradeStatus.WON, 1), else_=0)), 0).label(
            "wins"
        ),
        func.coalesce(func.sum(case((Trade.status == TradeStatus.LOST, 1), else_=0)), 0).label(
            "losses"
        ),
    ).where(
        Trade.user_id == user.id,
        Trade.status.in_(_SETTLED_STATUSES),
        func.date(Trade.trade_date) == yesterday_et,
    )
    yesterday_result = await db.execute(yesterday_query)
    yesterday_row = yesterday_result.one()
    yesterday_stats = PeriodStats(
        pnl_cents=int(yesterday_row.pnl),
        wins=int(yesterday_row.wins),
        losses=int(yesterday_row.losses),
    )

    # Query remaining periods with >= date filter
    week_stats = await _query_period(db, user.id, week_start)
    month_stats = await _query_period(db, user.id, month_start)
    year_stats = await _query_period(db, user.id, year_start)
    all_time_stats = await _query_period(db, user.id, None)

    logger.info(
        "Dashboard stats fetched",
        extra={
            "data": {
                "user_id": user.id,
                "all_time_pnl": all_time_stats.pnl_cents,
                "all_time_record": f"{all_time_stats.wins}W/{all_time_stats.losses}L",
            }
        },
    )

    return DashboardStats(
        yesterday=yesterday_stats,
        week=week_stats,
        month=month_stats,
        year=year_stats,
        all_time=all_time_stats,
    )


@router.get("/cooldown", response_model=CooldownStatus)
async def get_cooldown_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CooldownStatus:
    """Get current cooldown state for the dashboard indicator.

    Queries today's DailyRiskState and determines if a per-loss or
    consecutive-loss cooldown is active, along with remaining time.

    Args:
        user: The authenticated user.
        db: Async database session.

    Returns:
        CooldownStatus with active state, type, and remaining time.
    """
    from backend.trading.risk_manager import get_trading_day

    now = datetime.now(ET)
    trading_day = get_trading_day()
    trading_day_dt = datetime.combine(trading_day, datetime.min.time())

    result = await db.execute(
        select(DailyRiskState).where(
            DailyRiskState.user_id == user.id,
            DailyRiskState.trading_day == trading_day_dt,
        )
    )
    state = result.scalar_one_or_none()

    if state is None:
        return CooldownStatus(is_active=False, consecutive_losses=0)

    consecutive_losses = state.consecutive_losses or 0

    if state.cooldown_until is not None:
        cooldown_until = state.cooldown_until
        if cooldown_until.tzinfo is None:
            cooldown_until = cooldown_until.replace(tzinfo=ET)

        if now < cooldown_until:
            remaining = int((cooldown_until - now).total_seconds() / 60)

            # Determine cooldown type (rest-of-day = consecutive loss)
            from backend.trading.cooldown import _get_end_of_trading_day

            end_of_day = _get_end_of_trading_day()
            if cooldown_until.tzinfo is None:
                end_of_day_naive = end_of_day.replace(tzinfo=None)
                is_rest_of_day = abs((cooldown_until - end_of_day_naive).total_seconds()) < 60
            else:
                is_rest_of_day = abs((cooldown_until - end_of_day).total_seconds()) < 60

            # Check if toggle is off — if so, report as inactive
            settings = user_to_settings(user)
            if is_rest_of_day and not settings.enable_consecutive_loss_limit:
                return CooldownStatus(is_active=False, consecutive_losses=consecutive_losses)
            if not is_rest_of_day and not settings.enable_per_loss_cooldown:
                return CooldownStatus(is_active=False, consecutive_losses=consecutive_losses)

            cooldown_type = "consecutive_loss" if is_rest_of_day else "per_loss"

            # Store as naive UTC for serialization
            cooldown_until_utc = cooldown_until.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

            return CooldownStatus(
                is_active=True,
                cooldown_type=cooldown_type,
                cooldown_until=cooldown_until_utc,
                remaining_minutes=remaining,
                consecutive_losses=consecutive_losses,
            )

    return CooldownStatus(is_active=False, consecutive_losses=consecutive_losses)

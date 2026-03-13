"""Tests for the dashboard stats API endpoint (/api/dashboard/stats).

Verifies time-period P&L and W/L aggregation for yesterday, week,
month, year, and all-time windows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.models import TradeStatus
from tests.api.conftest import make_trade

pytestmark = pytest.mark.asyncio

ET = ZoneInfo("America/New_York")


async def test_stats_empty(client: AsyncClient) -> None:
    """GET /api/dashboard/stats returns all-zero stats when no trades exist."""
    response = await client.get("/api/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    for period in ("yesterday", "week", "month", "year", "all_time"):
        assert data[period]["pnl_cents"] == 0
        assert data[period]["wins"] == 0
        assert data[period]["losses"] == 0


async def test_stats_with_today_trade(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """A settled trade from today appears in week, month, year, all_time but NOT yesterday."""
    today_et = datetime.now(ET).date()
    trade = make_trade(
        user_id="test-user-001",
        status=TradeStatus.WON,
        pnl_cents=100,
        trade_date=today_et,
        settled_at=datetime.now(UTC),
    )
    db.add(trade)
    await db.flush()

    response = await client.get("/api/dashboard/stats")
    assert response.status_code == 200
    data = response.json()

    # Today's trade should NOT appear in yesterday
    assert data["yesterday"]["pnl_cents"] == 0
    assert data["yesterday"]["wins"] == 0

    # Should appear in week, month, year, all_time
    assert data["week"]["pnl_cents"] == 100
    assert data["week"]["wins"] == 1
    assert data["month"]["pnl_cents"] == 100
    assert data["year"]["pnl_cents"] == 100
    assert data["all_time"]["pnl_cents"] == 100
    assert data["all_time"]["wins"] == 1
    assert data["all_time"]["losses"] == 0


async def test_stats_yesterday_trade(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """A settled trade from yesterday appears in yesterday, week, month, year, all_time."""
    yesterday_et = datetime.now(ET).date() - timedelta(days=1)
    trade = make_trade(
        user_id="test-user-001",
        status=TradeStatus.LOST,
        pnl_cents=-50,
        trade_date=yesterday_et,
        settled_at=datetime.now(UTC),
    )
    db.add(trade)
    await db.flush()

    response = await client.get("/api/dashboard/stats")
    assert response.status_code == 200
    data = response.json()

    assert data["yesterday"]["pnl_cents"] == -50
    assert data["yesterday"]["losses"] == 1
    assert data["yesterday"]["wins"] == 0

    assert data["week"]["pnl_cents"] == -50
    assert data["month"]["pnl_cents"] == -50
    assert data["all_time"]["pnl_cents"] == -50


async def test_stats_old_trade_not_in_week(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """A trade from 15 days ago appears in month/year/all_time but not yesterday/week."""
    old_date = datetime.now(ET).date() - timedelta(days=15)
    trade = make_trade(
        user_id="test-user-001",
        status=TradeStatus.WON,
        pnl_cents=200,
        trade_date=old_date,
        settled_at=datetime.now(UTC),
    )
    db.add(trade)
    await db.flush()

    response = await client.get("/api/dashboard/stats")
    assert response.status_code == 200
    data = response.json()

    assert data["yesterday"]["pnl_cents"] == 0
    assert data["week"]["pnl_cents"] == 0
    assert data["month"]["pnl_cents"] == 200
    assert data["year"]["pnl_cents"] == 200
    assert data["all_time"]["pnl_cents"] == 200


async def test_stats_multiple_trades_aggregate(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Multiple trades in the same period aggregate correctly."""
    today_et = datetime.now(ET).date()
    for pnl, status in [(100, TradeStatus.WON), (-30, TradeStatus.LOST), (50, TradeStatus.WON)]:
        trade = make_trade(
            user_id="test-user-001",
            status=status,
            pnl_cents=pnl,
            trade_date=today_et,
            settled_at=datetime.now(UTC),
        )
        db.add(trade)
    await db.flush()

    response = await client.get("/api/dashboard/stats")
    assert response.status_code == 200
    data = response.json()

    assert data["week"]["pnl_cents"] == 120  # 100 - 30 + 50
    assert data["week"]["wins"] == 2
    assert data["week"]["losses"] == 1
    assert data["all_time"]["pnl_cents"] == 120


async def test_stats_open_trades_excluded(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """OPEN trades are NOT included in stats (only settled: WON/LOST)."""
    today_et = datetime.now(ET).date()
    open_trade = make_trade(
        user_id="test-user-001",
        status=TradeStatus.OPEN,
        trade_date=today_et,
    )
    db.add(open_trade)
    await db.flush()

    response = await client.get("/api/dashboard/stats")
    assert response.status_code == 200
    data = response.json()

    assert data["all_time"]["pnl_cents"] == 0
    assert data["all_time"]["wins"] == 0
    assert data["all_time"]["losses"] == 0


async def test_stats_unauthenticated(unauthed_client: AsyncClient) -> None:
    """GET /api/dashboard/stats returns 401 when not authenticated."""
    response = await unauthed_client.get("/api/dashboard/stats")
    assert response.status_code == 401


# ─── Cooldown Status Endpoint Tests ───


async def test_cooldown_status_no_cooldown(client: AsyncClient) -> None:
    """GET /api/dashboard/stats/cooldown returns inactive when no cooldown."""
    response = await client.get("/api/dashboard/stats/cooldown")
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is False
    assert data["cooldown_type"] is None
    assert data["cooldown_until"] is None
    assert data["remaining_minutes"] is None
    assert data["consecutive_losses"] == 0


async def test_cooldown_status_per_loss_active(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/dashboard/stats/cooldown returns per_loss when per-loss cooldown is active."""
    from backend.common.models import DailyRiskState

    today_et = datetime.now(ET).date()
    # Store as naive ET (TZNaiveDateTime strips tzinfo; endpoint re-adds ET)
    future_et = datetime.now(ET).replace(tzinfo=None) + timedelta(minutes=30)
    state = DailyRiskState(
        user_id="test-user-001",
        trading_day=today_et,
        cooldown_until=future_et,
        consecutive_losses=1,
    )
    db.add(state)
    await db.flush()

    response = await client.get("/api/dashboard/stats/cooldown")
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is True
    assert data["cooldown_type"] == "per_loss"
    assert data["remaining_minutes"] is not None
    assert data["remaining_minutes"] > 0
    assert data["consecutive_losses"] == 1


async def test_cooldown_status_consecutive_loss_active(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/dashboard/stats/cooldown returns consecutive_loss for rest-of-day cooldown."""
    from backend.common.models import DailyRiskState

    today_et = datetime.now(ET).date()
    # Store as naive ET 23:59:59 (matches _get_end_of_trading_day() after tzinfo strip)
    end_of_day_naive = datetime(today_et.year, today_et.month, today_et.day, 23, 59, 59)
    state = DailyRiskState(
        user_id="test-user-001",
        trading_day=today_et,
        cooldown_until=end_of_day_naive,
        consecutive_losses=3,
    )
    db.add(state)
    await db.flush()

    response = await client.get("/api/dashboard/stats/cooldown")
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is True
    assert data["cooldown_type"] == "consecutive_loss"
    assert data["consecutive_losses"] == 3


async def test_cooldown_status_unauthenticated(unauthed_client: AsyncClient) -> None:
    """GET /api/dashboard/stats/cooldown returns 401 when not authenticated."""
    response = await unauthed_client.get("/api/dashboard/stats/cooldown")
    assert response.status_code == 401

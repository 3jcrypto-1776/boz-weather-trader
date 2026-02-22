"""Calendar endpoint tests — daily aggregation, weekly summaries, monthly totals."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.models import TradeStatus
from tests.api.conftest import make_trade

pytestmark = pytest.mark.asyncio


async def test_calendar_empty(client: AsyncClient) -> None:
    """Empty month returns zero totals and no days/weeks."""
    resp = await client.get("/api/trades/calendar?year=2026&month=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["year"] == 2026
    assert data["month"] == 1
    assert data["days"] == []
    assert data["weeks"] == []
    assert data["total_pnl_cents"] == 0
    assert data["total_trades"] == 0
    assert data["trading_days"] == 0


async def test_calendar_with_trades(client: AsyncClient, db: AsyncSession) -> None:
    """Returns correct daily aggregation for a month with trades."""
    # Two trades on Feb 10 (1 won, 1 lost), one on Feb 15
    t1 = make_trade(
        "test-user-001",
        city="NYC",
        status=TradeStatus.WON,
        pnl_cents=75,
        trade_date=date(2026, 2, 10),
        settled_at=datetime(2026, 2, 10, 18, 0),
    )
    t2 = make_trade(
        "test-user-001",
        city="NYC",
        status=TradeStatus.LOST,
        pnl_cents=-25,
        trade_date=date(2026, 2, 10),
        settled_at=datetime(2026, 2, 10, 18, 0),
    )
    t3 = make_trade(
        "test-user-001",
        city="CHI",
        status=TradeStatus.WON,
        pnl_cents=100,
        trade_date=date(2026, 2, 15),
        settled_at=datetime(2026, 2, 15, 18, 0),
    )
    db.add_all([t1, t2, t3])
    await db.flush()

    resp = await client.get("/api/trades/calendar?year=2026&month=2")
    assert resp.status_code == 200
    data = resp.json()

    assert data["trading_days"] == 2
    assert data["total_trades"] == 3
    assert data["total_wins"] == 2
    assert data["total_losses"] == 1
    assert data["total_pnl_cents"] == 150  # 75 - 25 + 100

    # Check daily breakdown
    day_map = {d["date"]: d for d in data["days"]}
    assert "2026-02-10" in day_map
    feb10 = day_map["2026-02-10"]
    assert feb10["trade_count"] == 2
    assert feb10["wins"] == 1
    assert feb10["losses"] == 1
    assert feb10["pnl_cents"] == 50  # 75 - 25

    assert "2026-02-15" in day_map
    feb15 = day_map["2026-02-15"]
    assert feb15["trade_count"] == 1
    assert feb15["wins"] == 1
    assert feb15["pnl_cents"] == 100


async def test_calendar_win_rate(client: AsyncClient, db: AsyncSession) -> None:
    """Win rate is correctly computed per day."""
    # 3 trades on same day: 2 won, 1 lost → 66.67% win rate
    for pnl, status in [(50, TradeStatus.WON), (30, TradeStatus.WON), (-25, TradeStatus.LOST)]:
        t = make_trade(
            "test-user-001",
            status=status,
            pnl_cents=pnl,
            trade_date=date(2026, 3, 5),
            settled_at=datetime(2026, 3, 5, 18, 0),
        )
        db.add(t)
    await db.flush()

    resp = await client.get("/api/trades/calendar?year=2026&month=3")
    data = resp.json()
    day = data["days"][0]
    assert day["win_rate"] == pytest.approx(0.6667, abs=0.001)


async def test_calendar_weekly_summaries(client: AsyncClient, db: AsyncSession) -> None:
    """Weekly summaries aggregate daily data by ISO week."""
    # Two days in the same week (Mon Feb 9 and Wed Feb 11, 2026)
    t1 = make_trade(
        "test-user-001",
        status=TradeStatus.WON,
        pnl_cents=100,
        trade_date=date(2026, 2, 9),
        settled_at=datetime(2026, 2, 9, 18, 0),
    )
    t2 = make_trade(
        "test-user-001",
        status=TradeStatus.WON,
        pnl_cents=50,
        trade_date=date(2026, 2, 11),
        settled_at=datetime(2026, 2, 11, 18, 0),
    )
    db.add_all([t1, t2])
    await db.flush()

    resp = await client.get("/api/trades/calendar?year=2026&month=2")
    data = resp.json()

    assert len(data["weeks"]) == 1
    week = data["weeks"][0]
    assert week["pnl_cents"] == 150
    assert week["trade_count"] == 2
    assert week["trading_days"] == 2


async def test_calendar_filters_by_month(client: AsyncClient, db: AsyncSession) -> None:
    """Only returns data for the requested month."""
    t_jan = make_trade(
        "test-user-001",
        status=TradeStatus.WON,
        pnl_cents=100,
        trade_date=date(2026, 1, 15),
        settled_at=datetime(2026, 1, 15, 18, 0),
    )
    t_feb = make_trade(
        "test-user-001",
        status=TradeStatus.WON,
        pnl_cents=200,
        trade_date=date(2026, 2, 15),
        settled_at=datetime(2026, 2, 15, 18, 0),
    )
    db.add_all([t_jan, t_feb])
    await db.flush()

    # Request February only
    resp = await client.get("/api/trades/calendar?year=2026&month=2")
    data = resp.json()
    assert data["total_trades"] == 1
    assert data["total_pnl_cents"] == 200


async def test_calendar_excludes_open_trades(client: AsyncClient, db: AsyncSession) -> None:
    """Open trades are not included in calendar aggregation."""
    t_open = make_trade(
        "test-user-001",
        status=TradeStatus.OPEN,
        trade_date=date(2026, 2, 10),
    )
    t_won = make_trade(
        "test-user-001",
        status=TradeStatus.WON,
        pnl_cents=50,
        trade_date=date(2026, 2, 10),
        settled_at=datetime(2026, 2, 10, 18, 0),
    )
    db.add_all([t_open, t_won])
    await db.flush()

    resp = await client.get("/api/trades/calendar?year=2026&month=2")
    data = resp.json()
    assert data["total_trades"] == 1  # Only the settled trade


async def test_calendar_invalid_month(client: AsyncClient) -> None:
    """Invalid month returns 422 validation error."""
    resp = await client.get("/api/trades/calendar?year=2026&month=13")
    assert resp.status_code == 422


async def test_calendar_invalid_year(client: AsyncClient) -> None:
    """Invalid year returns 422 validation error."""
    resp = await client.get("/api/trades/calendar?year=2023&month=1")
    assert resp.status_code == 422


async def test_calendar_unauthenticated(unauthed_client: AsyncClient) -> None:
    """Unauthenticated request returns 401."""
    resp = await unauthed_client.get("/api/trades/calendar?year=2026&month=2")
    assert resp.status_code == 401

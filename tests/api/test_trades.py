"""Tests for the trades API endpoint."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.models import CityEnum, Settlement, TradeStatus
from tests.api.conftest import make_trade

pytestmark = pytest.mark.asyncio


async def test_trades_empty(client: AsyncClient) -> None:
    """GET /api/trades returns empty page when no trades exist."""
    response = await client.get("/api/trades")
    assert response.status_code == 200
    data = response.json()
    assert data["trades"] == []
    assert data["total"] == 0
    assert data["page"] == 1


async def test_trades_pagination(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/trades supports pagination."""
    # Add 25 trades to exceed default page size (20)
    for _ in range(25):
        trade = make_trade(user_id="test-user-001", status=TradeStatus.OPEN)
        db.add(trade)
    await db.flush()

    # First page
    response = await client.get("/api/trades", params={"page": 1})
    assert response.status_code == 200
    data = response.json()
    assert len(data["trades"]) == 20
    assert data["total"] == 25
    assert data["page"] == 1

    # Second page
    response = await client.get("/api/trades", params={"page": 2})
    data = response.json()
    assert len(data["trades"]) == 5
    assert data["total"] == 25
    assert data["page"] == 2


async def test_trades_city_filter(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/trades?city=NYC filters by city."""
    nyc_trade = make_trade(user_id="test-user-001", city="NYC")
    chi_trade = make_trade(user_id="test-user-001", city="CHI")
    db.add(nyc_trade)
    db.add(chi_trade)
    await db.flush()

    response = await client.get("/api/trades", params={"city": "NYC"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["trades"][0]["city"] == "NYC"


async def test_trades_status_filter(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/trades?status=WON filters by status."""
    open_trade = make_trade(user_id="test-user-001", status=TradeStatus.OPEN)
    won_trade = make_trade(user_id="test-user-001", status=TradeStatus.WON, pnl_cents=50)
    db.add(open_trade)
    db.add(won_trade)
    await db.flush()

    response = await client.get("/api/trades", params={"status": "WON"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["trades"][0]["status"] == "WON"


async def test_trades_date_filter(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/trades?trade_date=YYYY-MM-DD filters by date."""
    t1 = make_trade(
        user_id="test-user-001",
        trade_date=date(2026, 2, 10),
    )
    t2 = make_trade(
        user_id="test-user-001",
        trade_date=date(2026, 2, 15),
    )
    db.add(t1)
    db.add(t2)
    await db.flush()

    response = await client.get("/api/trades", params={"trade_date": "2026-02-10"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["trades"][0]["date"] == "2026-02-10"


async def test_trades_date_filter_no_match(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/trades?trade_date returns empty when no trades on that date."""
    t = make_trade(
        user_id="test-user-001",
        trade_date=date(2026, 2, 10),
    )
    db.add(t)
    await db.flush()

    response = await client.get("/api/trades", params={"trade_date": "2026-02-20"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["trades"] == []


async def test_trades_settled_status_filter(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/trades?status=SETTLED returns WON+LOST+CANCELED, excludes OPEN."""
    open_trade = make_trade(user_id="test-user-001", status=TradeStatus.OPEN)
    won_trade = make_trade(user_id="test-user-001", status=TradeStatus.WON, pnl_cents=50)
    lost_trade = make_trade(user_id="test-user-001", status=TradeStatus.LOST, pnl_cents=-25)
    canceled_trade = make_trade(user_id="test-user-001", status=TradeStatus.CANCELED)
    db.add(open_trade)
    db.add(won_trade)
    db.add(lost_trade)
    db.add(canceled_trade)
    await db.flush()

    response = await client.get("/api/trades", params={"status": "SETTLED"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    statuses = {t["status"] for t in data["trades"]}
    assert "OPEN" not in statuses
    assert "WON" in statuses
    assert "LOST" in statuses
    assert "CANCELED" in statuses


async def test_trades_unauthenticated(unauthed_client: AsyncClient) -> None:
    """GET /api/trades returns 401 when not authenticated."""
    response = await unauthed_client.get("/api/trades")
    assert response.status_code == 401


async def test_settle_resettle_fixes_mismarked_trades(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """POST /api/trades/settle?resettle=true resets and re-settles all trades.

    Simulates the bracket parsing bug fix: a trade that was incorrectly LOST
    (bracket '71° to 72°F', actual 72°F) should become WON after re-settlement.
    """
    market_date = date(2026, 2, 25)

    # Create a settlement record for the market date
    settlement = Settlement(
        city=CityEnum.MIA,
        settlement_date=datetime(2026, 2, 25),
        actual_high_f=72.0,
        actual_low_f=60.0,
        source="NWS_CLI",
    )
    db.add(settlement)

    # Create a trade that was incorrectly marked LOST (bracket parsing bug)
    trade = make_trade(
        user_id="test-user-001",
        city="MIA",
        status=TradeStatus.LOST,
        pnl_cents=-10,
        trade_date=date(2026, 2, 24),
        market_date=market_date,
        bracket_label="71\u00b0 to 72\u00b0F",
        side="yes",
        price_cents=10,
        settlement_temp_f=72.0,
        market_ticker="KXHIGHMIA-26FEB25-B71.5",
    )
    db.add(trade)
    await db.commit()

    # Verify trade starts as LOST
    resp = await client.get("/api/trades", params={"status": "LOST"})
    assert resp.json()["total"] == 1

    # Trigger re-settlement (mock NWS fetch to avoid external calls)
    with patch(
        "backend.weather.nws.fetch_all_nws_cli",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = await client.post("/api/trades/settle", params={"resettle": "true"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["reset_count"] == 1
    assert data["settled_count"] == 1

    # Trade should now be WON (72°F is within 71-72°F bracket)
    resp = await client.get("/api/trades", params={"status": "WON"})
    won_data = resp.json()
    assert won_data["total"] == 1
    assert won_data["trades"][0]["status"] == "WON"
    assert won_data["trades"][0]["pnl_cents"] > 0

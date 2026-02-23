"""Tests for the logs API endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.conftest import make_log_entry

pytestmark = pytest.mark.asyncio


async def test_logs_empty(client: AsyncClient) -> None:
    """GET /api/logs returns empty list when no log entries exist."""
    response = await client.get("/api/logs")
    assert response.status_code == 200
    assert response.json() == []


async def test_logs_returns_entries(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/logs returns log entries."""
    entry1 = make_log_entry(module_tag="TRADING", level="INFO", message="Trade placed")
    entry2 = make_log_entry(module_tag="ORDER", level="ERROR", message="Order failed")
    db.add(entry1)
    db.add(entry2)
    await db.flush()

    response = await client.get("/api/logs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


async def test_logs_oldest_first_ordering(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/logs returns entries oldest-first (newest at bottom for auto-scroll)."""
    entry1 = make_log_entry(module_tag="TRADING", message="First")
    entry1.timestamp = datetime(2026, 1, 1, 10, 0, 0)
    entry2 = make_log_entry(module_tag="TRADING", message="Second")
    entry2.timestamp = datetime(2026, 1, 1, 10, 0, 0) + timedelta(seconds=5)
    db.add(entry1)
    db.add(entry2)
    await db.flush()

    response = await client.get("/api/logs")
    data = response.json()
    assert data[0]["message"] == "First"
    assert data[1]["message"] == "Second"


async def test_logs_module_filter_exact(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/logs?module=WEATHER filters to WEATHER tag only."""
    db.add(make_log_entry(module_tag="WEATHER", message="Forecast fetched"))
    db.add(make_log_entry(module_tag="TRADING", message="Trade placed"))
    await db.flush()

    response = await client.get("/api/logs", params={"module": "WEATHER"})
    data = response.json()
    assert len(data) == 1
    assert data[0]["module"] == "WEATHER"


async def test_logs_prediction_filter_maps_to_model(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """PREDICTION filter maps to the MODEL backend tag."""
    db.add(make_log_entry(module_tag="MODEL", message="Prediction generated"))
    db.add(make_log_entry(module_tag="WEATHER", message="Forecast fetched"))
    await db.flush()

    response = await client.get("/api/logs", params={"module": "PREDICTION"})
    data = response.json()
    assert len(data) == 1
    assert data[0]["module"] == "MODEL"


async def test_logs_trading_filter_includes_related_tags(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """TRADING filter includes ORDER, RISK, COOLDOWN, SETTLE, POSTMORTEM tags."""
    db.add(make_log_entry(module_tag="TRADING", message="Cycle start"))
    db.add(make_log_entry(module_tag="ORDER", message="Order placed"))
    db.add(make_log_entry(module_tag="RISK", message="Risk check"))
    db.add(make_log_entry(module_tag="COOLDOWN", message="Cooldown active"))
    db.add(make_log_entry(module_tag="SETTLE", message="Settlement"))
    db.add(make_log_entry(module_tag="WEATHER", message="Forecast"))
    await db.flush()

    response = await client.get("/api/logs", params={"module": "TRADING"})
    data = response.json()
    assert len(data) == 5
    modules = {entry["module"] for entry in data}
    assert modules == {"TRADING", "ORDER", "RISK", "COOLDOWN", "SETTLE"}


async def test_logs_system_filter_includes_auth(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """SYSTEM filter includes AUTH and MARKET tags."""
    db.add(make_log_entry(module_tag="SYSTEM", message="App started"))
    db.add(make_log_entry(module_tag="AUTH", message="User login"))
    db.add(make_log_entry(module_tag="TRADING", message="Trade"))
    await db.flush()

    response = await client.get("/api/logs", params={"module": "SYSTEM"})
    data = response.json()
    assert len(data) == 2
    modules = {entry["module"] for entry in data}
    assert "TRADING" not in modules


async def test_logs_level_filter(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/logs?level=ERROR filters by log level."""
    info_entry = make_log_entry(level="INFO", message="Normal operation")
    error_entry = make_log_entry(level="ERROR", message="Something broke")
    db.add(info_entry)
    db.add(error_entry)
    await db.flush()

    response = await client.get("/api/logs", params={"level": "ERROR"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["level"] == "ERROR"


async def test_logs_after_filter(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """GET /api/logs?after=<timestamp> filters by timestamp."""
    entry = make_log_entry(message="Recent log")
    db.add(entry)
    await db.flush()

    # Use a future date to get no results
    response = await client.get(
        "/api/logs",
        params={"after": "2099-01-01T00:00:00"},
    )
    assert response.status_code == 200
    assert response.json() == []


async def test_logs_unauthenticated(unauthed_client: AsyncClient) -> None:
    """GET /api/logs returns 401 when not authenticated."""
    response = await unauthed_client.get("/api/logs")
    assert response.status_code == 401

"""Tests for the settings API endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_get_settings(client: AsyncClient) -> None:
    """GET /api/settings returns current user settings."""
    response = await client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["trading_mode"] == "manual"
    assert data["max_trade_size_cents"] == 100
    assert data["daily_loss_limit_cents"] == 1000
    assert data["max_daily_exposure_cents"] == 2500
    assert data["min_ev_threshold"] == 0.05
    assert data["cooldown_per_loss_minutes"] == 60
    assert data["consecutive_loss_limit"] == 3
    assert set(data["active_cities"]) == {"NYC", "CHI", "MIA", "AUS"}
    assert data["notifications_enabled"] is True


async def test_patch_settings_partial(client: AsyncClient) -> None:
    """PATCH /api/settings updates only the provided fields."""
    response = await client.patch(
        "/api/settings",
        json={"trading_mode": "auto", "max_trade_size_cents": 200},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["trading_mode"] == "auto"
    assert data["max_trade_size_cents"] == 200
    # Unchanged fields remain the same
    assert data["daily_loss_limit_cents"] == 1000


async def test_patch_settings_active_cities(client: AsyncClient) -> None:
    """PATCH /api/settings can update active_cities list."""
    response = await client.patch(
        "/api/settings",
        json={"active_cities": ["NYC", "MIA"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert set(data["active_cities"]) == {"NYC", "MIA"}


async def test_patch_settings_empty_body(client: AsyncClient) -> None:
    """PATCH /api/settings with empty body returns current settings unchanged."""
    # First get current settings
    get_resp = await client.get("/api/settings")
    original = get_resp.json()

    # Patch with empty body
    patch_resp = await client.patch("/api/settings", json={})
    assert patch_resp.status_code == 200
    patched = patch_resp.json()

    # trading_mode should be unchanged from previous tests or default
    assert patched["daily_loss_limit_cents"] == original["daily_loss_limit_cents"]


async def test_get_settings_unauthenticated(unauthed_client: AsyncClient) -> None:
    """GET /api/settings returns 401 when not authenticated."""
    response = await unauthed_client.get("/api/settings")
    assert response.status_code == 401


async def test_get_settings_includes_bracket_cap_defaults(client: AsyncClient) -> None:
    """GET /api/settings includes max_contracts_per_bracket and enable_consecutive_loss_limit."""
    response = await client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["max_contracts_per_bracket"] == 3
    assert data["enable_consecutive_loss_limit"] is True


async def test_patch_bracket_cap(client: AsyncClient) -> None:
    """PATCH /api/settings can update max_contracts_per_bracket."""
    response = await client.patch(
        "/api/settings",
        json={"max_contracts_per_bracket": 10},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["max_contracts_per_bracket"] == 10

    # Verify it persists on GET
    get_resp = await client.get("/api/settings")
    assert get_resp.json()["max_contracts_per_bracket"] == 10


async def test_patch_consecutive_loss_toggle(client: AsyncClient) -> None:
    """PATCH /api/settings can toggle enable_consecutive_loss_limit."""
    response = await client.patch(
        "/api/settings",
        json={"enable_consecutive_loss_limit": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["enable_consecutive_loss_limit"] is False

    # Verify it persists on GET
    get_resp = await client.get("/api/settings")
    assert get_resp.json()["enable_consecutive_loss_limit"] is False


async def test_get_settings_includes_per_loss_cooldown_toggle(client: AsyncClient) -> None:
    """GET /api/settings includes enable_per_loss_cooldown (defaults to True)."""
    response = await client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["enable_per_loss_cooldown"] is True


async def test_patch_per_loss_cooldown_toggle(client: AsyncClient) -> None:
    """PATCH /api/settings can toggle enable_per_loss_cooldown."""
    response = await client.patch(
        "/api/settings",
        json={"enable_per_loss_cooldown": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["enable_per_loss_cooldown"] is False

    # Verify it persists on GET
    get_resp = await client.get("/api/settings")
    assert get_resp.json()["enable_per_loss_cooldown"] is False


async def test_get_settings_includes_timezone_default(client: AsyncClient) -> None:
    """GET /api/settings includes timezone (defaults to empty string = browser default)."""
    response = await client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["timezone"] == ""


async def test_patch_timezone(client: AsyncClient) -> None:
    """PATCH /api/settings can update timezone to an IANA timezone string."""
    response = await client.patch(
        "/api/settings",
        json={"timezone": "America/Chicago"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["timezone"] == "America/Chicago"

    # Verify it persists on GET
    get_resp = await client.get("/api/settings")
    assert get_resp.json()["timezone"] == "America/Chicago"


async def test_patch_timezone_to_browser_default(client: AsyncClient) -> None:
    """PATCH /api/settings can reset timezone to empty string (browser default)."""
    # Set a timezone first
    await client.patch("/api/settings", json={"timezone": "America/New_York"})

    # Reset to browser default
    response = await client.patch("/api/settings", json={"timezone": ""})
    assert response.status_code == 200
    assert response.json()["timezone"] == ""

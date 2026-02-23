"""Tests for GET /api/weather/current — current weather ticker endpoint."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OPEN_METEO_RESPONSE = {
    "current_weather": {"temperature": 52.3},
    "daily": {
        "temperature_2m_max": [58.1],
        "temperature_2m_min": [39.7],
    },
}


_FAKE_REQUEST = httpx.Request("GET", "https://api.open-meteo.com/v1/forecast")


def _make_meteo_response(
    temp: float = 52.3,
    high: float = 58.1,
    low: float = 39.7,
    *,
    status_code: int = 200,
) -> httpx.Response:
    """Create a mock Open-Meteo httpx.Response."""
    data = {
        "current_weather": {"temperature": temp},
        "daily": {
            "temperature_2m_max": [high],
            "temperature_2m_min": [low],
        },
    }
    return httpx.Response(status_code=status_code, json=data, request=_FAKE_REQUEST)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weather_current_returns_all_cities(client: AsyncClient) -> None:
    """Happy path — all 4 cities return successfully."""
    mock_get = AsyncMock(return_value=_make_meteo_response())

    with patch("backend.api.weather.httpx.AsyncClient") as MockClient:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        ctx.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = ctx

        # Clear cache so we always fetch fresh
        import backend.api.weather as weather_mod

        weather_mod._weather_cache = {}
        weather_mod._weather_cache_time = 0.0

        response = await client.get("/api/weather/current")

    assert response.status_code == 200
    data = response.json()
    assert "cities" in data
    assert "fetched_at" in data
    assert len(data["cities"]) == 4

    # Verify each city block has required fields
    city_codes = {c["city"] for c in data["cities"]}
    assert city_codes == {"NYC", "CHI", "MIA", "AUS"}

    for city in data["cities"]:
        assert "city_name" in city
        assert "current_temp_f" in city
        assert "today_high_f" in city
        assert "today_low_f" in city


@pytest.mark.asyncio
async def test_weather_current_response_shape(client: AsyncClient) -> None:
    """Verify exact field types in the response."""
    mock_get = AsyncMock(return_value=_make_meteo_response(temp=70.0, high=75.5, low=60.2))

    with patch("backend.api.weather.httpx.AsyncClient") as MockClient:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        ctx.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = ctx

        import backend.api.weather as weather_mod

        weather_mod._weather_cache = {}
        weather_mod._weather_cache_time = 0.0

        response = await client.get("/api/weather/current")

    data = response.json()
    city = data["cities"][0]
    assert isinstance(city["current_temp_f"], float)
    assert isinstance(city["today_high_f"], float)
    assert isinstance(city["today_low_f"], float)
    assert city["current_temp_f"] == 70.0
    assert city["today_high_f"] == 75.5
    assert city["today_low_f"] == 60.2


@pytest.mark.asyncio
async def test_weather_current_no_auth_required(unauthed_client: AsyncClient) -> None:
    """Weather endpoint should NOT require authentication."""
    mock_get = AsyncMock(return_value=_make_meteo_response())

    with patch("backend.api.weather.httpx.AsyncClient") as MockClient:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        ctx.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = ctx

        import backend.api.weather as weather_mod

        weather_mod._weather_cache = {}
        weather_mod._weather_cache_time = 0.0

        response = await unauthed_client.get("/api/weather/current")

    # Should succeed even without auth
    assert response.status_code == 200
    data = response.json()
    assert len(data["cities"]) == 4


@pytest.mark.asyncio
async def test_weather_cache_returns_cached_data(client: AsyncClient) -> None:
    """Second request within TTL should return cached data without re-fetching."""
    mock_get = AsyncMock(return_value=_make_meteo_response(temp=55.0))

    with patch("backend.api.weather.httpx.AsyncClient") as MockClient:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        ctx.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = ctx

        import backend.api.weather as weather_mod

        weather_mod._weather_cache = {}
        weather_mod._weather_cache_time = 0.0

        # First request — populates cache
        response1 = await client.get("/api/weather/current")
        assert response1.status_code == 200
        call_count_after_first = mock_get.call_count

        # Second request — should use cache
        response2 = await client.get("/api/weather/current")
        assert response2.status_code == 200

    # Mock should NOT have been called again
    assert mock_get.call_count == call_count_after_first

    # Both responses should be identical
    assert response1.json() == response2.json()


@pytest.mark.asyncio
async def test_weather_cache_expires_after_ttl(client: AsyncClient) -> None:
    """After TTL expires, cache should be refreshed."""
    mock_get = AsyncMock(return_value=_make_meteo_response(temp=55.0))

    with patch("backend.api.weather.httpx.AsyncClient") as MockClient:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        ctx.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = ctx

        import backend.api.weather as weather_mod

        weather_mod._weather_cache = {}
        weather_mod._weather_cache_time = 0.0

        # First request
        await client.get("/api/weather/current")
        call_count_after_first = mock_get.call_count

        # Simulate cache expiry by moving the cache time backward
        weather_mod._weather_cache_time = time.monotonic() - 400  # 400s > 300s TTL

        # Second request — should re-fetch
        await client.get("/api/weather/current")

    assert mock_get.call_count > call_count_after_first


@pytest.mark.asyncio
async def test_weather_partial_failure_returns_available_cities(
    client: AsyncClient,
) -> None:
    """If some cities fail, the endpoint should still return the successful ones."""
    call_count = 0

    async def _selective_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Fail every other city
        if call_count % 2 == 0:
            raise httpx.HTTPStatusError(
                "Service Unavailable",
                request=_FAKE_REQUEST,
                response=httpx.Response(503, request=_FAKE_REQUEST),
            )
        return _make_meteo_response()

    mock_get = AsyncMock(side_effect=_selective_get)

    with patch("backend.api.weather.httpx.AsyncClient") as MockClient:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        ctx.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = ctx

        import backend.api.weather as weather_mod

        weather_mod._weather_cache = {}
        weather_mod._weather_cache_time = 0.0

        response = await client.get("/api/weather/current")

    assert response.status_code == 200
    data = response.json()
    # Should have 2 out of 4 cities (odd calls succeed)
    assert len(data["cities"]) == 2


@pytest.mark.asyncio
async def test_weather_total_failure_returns_empty_cities(
    client: AsyncClient,
) -> None:
    """If ALL cities fail, the endpoint should return 200 with empty cities list."""
    mock_get = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Service Unavailable",
            request=_FAKE_REQUEST,
            response=httpx.Response(503, request=_FAKE_REQUEST),
        )
    )

    with patch("backend.api.weather.httpx.AsyncClient") as MockClient:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        ctx.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = ctx

        import backend.api.weather as weather_mod

        weather_mod._weather_cache = {}
        weather_mod._weather_cache_time = 0.0

        response = await client.get("/api/weather/current")

    assert response.status_code == 200
    data = response.json()
    assert data["cities"] == []
    assert "fetched_at" in data


@pytest.mark.asyncio
async def test_weather_fetched_at_is_utc_with_z_suffix(
    client: AsyncClient,
) -> None:
    """fetched_at should be a UTC ISO timestamp ending with 'Z'."""
    mock_get = AsyncMock(return_value=_make_meteo_response())

    with patch("backend.api.weather.httpx.AsyncClient") as MockClient:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
        ctx.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = ctx

        import backend.api.weather as weather_mod

        weather_mod._weather_cache = {}
        weather_mod._weather_cache_time = 0.0

        response = await client.get("/api/weather/current")

    data = response.json()
    assert data["fetched_at"].endswith("Z")

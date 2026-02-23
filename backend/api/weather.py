"""Current weather endpoint for the frontend weather ticker.

Provides current temperature + today's high/low for all 4 market cities.
Uses Open-Meteo API with in-memory caching (5-minute TTL).

No authentication required — weather data is public and this endpoint
is needed on every page load before auth may be configured.

Usage:
    GET /api/weather/current
    → { cities: [...], fetched_at: "2026-02-23T17:05:00Z" }
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter

from backend.api.response_schemas import (
    CityCurrentWeather,
    CurrentWeatherResponse,
)
from backend.common.logging import get_logger
from backend.weather.stations import STATION_CONFIGS

logger = get_logger("WEATHER")

router = APIRouter()

# ─── In-Memory Cache ───

CACHE_TTL_SECONDS = 300  # 5 minutes

_weather_cache: dict[str, Any] = {}
_weather_cache_time: float = 0.0

CITY_NAMES: dict[str, str] = {
    "NYC": "New York",
    "CHI": "Chicago",
    "MIA": "Miami",
    "AUS": "Austin",
}

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"


async def _fetch_city_weather(
    client: httpx.AsyncClient,
    city: str,
) -> CityCurrentWeather | None:
    """Fetch current weather for a single city from Open-Meteo.

    Returns None if the fetch fails (graceful degradation).
    """
    config = STATION_CONFIGS.get(city)
    if config is None:
        return None

    try:
        resp = await client.get(
            OPEN_METEO_BASE,
            params={
                "latitude": config.lat,
                "longitude": config.lon,
                "current_weather": "true",
                "daily": "temperature_2m_max,temperature_2m_min",
                "temperature_unit": "fahrenheit",
                "timezone": str(config.timezone),
                "forecast_days": 1,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        current = data.get("current_weather", {})
        daily = data.get("daily", {})

        current_temp = current.get("temperature")
        highs = daily.get("temperature_2m_max", [])
        lows = daily.get("temperature_2m_min", [])

        if current_temp is None or not highs or not lows:
            logger.warning(
                "Incomplete weather data from Open-Meteo",
                extra={"data": {"city": city}},
            )
            return None

        return CityCurrentWeather(
            city=city,
            city_name=CITY_NAMES.get(city, city),
            current_temp_f=round(current_temp, 1),
            today_high_f=round(highs[0], 1),
            today_low_f=round(lows[0], 1),
        )
    except Exception as exc:
        logger.warning(
            "Failed to fetch current weather",
            extra={"data": {"city": city, "error": str(exc)}},
        )
        return None


async def _fetch_all_current_weather() -> CurrentWeatherResponse:
    """Fetch current weather for all cities concurrently.

    Uses asyncio.gather with return_exceptions=True so one city's
    failure doesn't block the others.
    """
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_city_weather(client, city) for city in STATION_CONFIGS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    cities: list[CityCurrentWeather] = []
    for result in results:
        if isinstance(result, CityCurrentWeather):
            cities.append(result)
        # Exceptions and None results are silently skipped

    return CurrentWeatherResponse(
        cities=cities,
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
    )


@router.get("/current", response_model=CurrentWeatherResponse)
async def get_current_weather() -> CurrentWeatherResponse:
    """Get current temperature + today's high/low for all market cities.

    Responses are cached in-memory for 5 minutes to avoid
    hammering the Open-Meteo API on every page load.
    """
    global _weather_cache, _weather_cache_time  # noqa: PLW0603

    now = time.monotonic()
    if _weather_cache and (now - _weather_cache_time) < CACHE_TTL_SECONDS:
        return _weather_cache["data"]

    data = await _fetch_all_current_weather()

    _weather_cache = {"data": data}
    _weather_cache_time = now

    logger.info(
        "Weather cache refreshed",
        extra={"data": {"cities": len(data.cities)}},
    )

    return data

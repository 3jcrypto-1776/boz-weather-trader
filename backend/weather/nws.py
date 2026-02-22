"""NWS (National Weather Service) API client.

Handles fetching forecast data from the NWS API (api.weather.gov),
including period forecasts (12-hour blocks), raw gridpoint data, and
CLI (Daily Climate Report) text products for settlement.

Key endpoints used:
  - /points/{lat},{lon}          -> Grid coordinate lookup (cached)
  - /gridpoints/{o}/{x},{y}/forecast  -> Period forecasts (Fahrenheit)
  - /gridpoints/{o}/{x},{y}          -> Raw gridpoint data (Celsius!)
  - /products/types/CLI/locations/{loc} -> CLI product listing
  - /products/{id}               -> CLI product text (settlement temps)

All fetch operations include exponential backoff retry logic and
rate limiting to respect NWS API guidelines.
"""

from __future__ import annotations

import asyncio

import httpx

from backend.common.config import get_settings
from backend.common.logging import get_logger
from backend.common.schemas import WeatherData
from backend.weather.exceptions import FetchError, ParseError
from backend.weather.normalizer import (
    normalize_nws_forecast,
    normalize_nws_gridpoint,
)
from backend.weather.rate_limiter import nws_limiter
from backend.weather.stations import STATION_CONFIGS

logger = get_logger("WEATHER")

NWS_BASE_URL = "https://api.weather.gov"


# ─── Generic HTTP Fetch ───


async def fetch_with_retry(
    url: str,
    max_retries: int = 3,
    headers: dict | None = None,
    params: dict | None = None,
) -> dict:
    """Fetch a URL with exponential backoff retry.

    Creates a NEW httpx.AsyncClient per call to avoid connection pooling
    issues across Celery tasks. Applies rate limiting before each attempt.

    Args:
        url: The URL to fetch.
        max_retries: Maximum number of retries after the initial attempt.
        headers: Optional HTTP headers (merged with default User-Agent).
        params: Optional query parameters.

    Returns:
        Parsed JSON response as a dict.

    Raises:
        FetchError: If all retries are exhausted.
    """
    settings = get_settings()
    default_headers = {"User-Agent": settings.nws_user_agent}
    if headers:
        default_headers.update(headers)

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            await nws_limiter.acquire()
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers=default_headers,
                    params=params,
                )
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as exc:
            last_error = exc
            status_code = exc.response.status_code

            if status_code >= 500 and attempt < max_retries:
                wait = 2**attempt  # 1s, 2s, 4s
                logger.warning(
                    f"NWS returned {status_code}, retrying",
                    extra={
                        "data": {
                            "url": url,
                            "status_code": status_code,
                            "attempt": attempt + 1,
                            "wait_seconds": wait,
                        }
                    },
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "HTTP error fetching URL",
                    extra={
                        "data": {
                            "url": url,
                            "status_code": status_code,
                            "attempts": attempt + 1,
                        }
                    },
                )
                raise FetchError(
                    f"HTTP {status_code} fetching {url} after {attempt + 1} attempts"
                ) from exc

        except httpx.RequestError as exc:
            last_error = exc

            if attempt < max_retries:
                wait = 2**attempt
                logger.warning(
                    "Network error, retrying",
                    extra={
                        "data": {
                            "url": url,
                            "error": str(exc),
                            "attempt": attempt + 1,
                            "wait_seconds": wait,
                        }
                    },
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "Network error fetching URL, all retries exhausted",
                    extra={"data": {"url": url, "error": str(exc)}},
                )
                raise FetchError(
                    f"Network error fetching {url} after {attempt + 1} attempts: {exc}"
                ) from exc

    # Should never reach here, but just in case
    raise FetchError(f"All retries exhausted for {url}") from last_error


async def fetch_text_with_retry(
    url: str,
    max_retries: int = 3,
    headers: dict | None = None,
    params: dict | None = None,
) -> str:
    """Fetch a URL and return the response as text (not JSON).

    Identical retry/rate-limit logic as fetch_with_retry, but returns
    response.text instead of response.json(). Used for NWS CLI products
    which return plain text, not JSON.

    Args:
        url: The URL to fetch.
        max_retries: Maximum number of retries after the initial attempt.
        headers: Optional HTTP headers (merged with default User-Agent).
        params: Optional query parameters.

    Returns:
        Response body as text string.

    Raises:
        FetchError: If all retries are exhausted.
    """
    settings = get_settings()
    default_headers = {"User-Agent": settings.nws_user_agent}
    if headers:
        default_headers.update(headers)

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            await nws_limiter.acquire()
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers=default_headers,
                    params=params,
                )
                response.raise_for_status()
                return response.text

        except httpx.HTTPStatusError as exc:
            last_error = exc
            status_code = exc.response.status_code

            if status_code >= 500 and attempt < max_retries:
                wait = 2**attempt
                logger.warning(
                    f"NWS returned {status_code}, retrying (text)",
                    extra={
                        "data": {
                            "url": url,
                            "status_code": status_code,
                            "attempt": attempt + 1,
                            "wait_seconds": wait,
                        }
                    },
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "HTTP error fetching text URL",
                    extra={
                        "data": {
                            "url": url,
                            "status_code": status_code,
                            "attempts": attempt + 1,
                        }
                    },
                )
                raise FetchError(
                    f"HTTP {status_code} fetching {url} after {attempt + 1} attempts"
                ) from exc

        except httpx.RequestError as exc:
            last_error = exc

            if attempt < max_retries:
                wait = 2**attempt
                logger.warning(
                    "Network error, retrying (text)",
                    extra={
                        "data": {
                            "url": url,
                            "error": str(exc),
                            "attempt": attempt + 1,
                            "wait_seconds": wait,
                        }
                    },
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "Network error fetching text URL, all retries exhausted",
                    extra={"data": {"url": url, "error": str(exc)}},
                )
                raise FetchError(
                    f"Network error fetching {url} after {attempt + 1} attempts: {exc}"
                ) from exc

    raise FetchError(f"All retries exhausted for {url}") from last_error


# ─── Grid Coordinate Lookup ───


async def get_grid_coordinates(city: str) -> dict:
    """Get NWS grid coordinates for a city. Cached after first call.

    Grid coordinates are geographic and never change, so we look them
    up once and cache them in the STATION_CONFIGS in-memory dict.

    Args:
        city: Kalshi city code (NYC, CHI, MIA, AUS).

    Returns:
        Dict with keys: 'office' (str), 'x' (int), 'y' (int).

    Raises:
        KeyError: If city is not a valid city code.
        FetchError: If the NWS API call fails.
        ParseError: If the response has unexpected structure.
    """
    config = STATION_CONFIGS[city]
    if config.grid is not None:
        return config.grid

    url = f"{NWS_BASE_URL}/points/{config.lat},{config.lon}"

    logger.info(
        "Looking up NWS grid coordinates",
        extra={"data": {"city": city, "lat": config.lat, "lon": config.lon}},
    )

    data = await fetch_with_retry(url)

    try:
        properties = data["properties"]
        grid = {
            "office": properties["gridId"],
            "x": properties["gridX"],
            "y": properties["gridY"],
        }
    except (KeyError, TypeError) as exc:
        raise ParseError(
            f"Unexpected NWS points response for {city}: missing required grid fields"
        ) from exc

    # Cache in memory so subsequent calls skip the API
    config.grid = grid

    logger.info(
        "Cached NWS grid coordinates",
        extra={"data": {"city": city, "grid": grid}},
    )

    return grid


# ─── URL Builders ───


async def build_forecast_url(city: str) -> str:
    """Build the NWS period forecast URL for a city.

    Args:
        city: Kalshi city code.

    Returns:
        Full URL for the NWS period forecast endpoint.
    """
    grid = await get_grid_coordinates(city)
    return f"{NWS_BASE_URL}/gridpoints/{grid['office']}/{grid['x']},{grid['y']}/forecast"


async def build_gridpoint_url(city: str) -> str:
    """Build the NWS raw gridpoint data URL for a city.

    Args:
        city: Kalshi city code.

    Returns:
        Full URL for the NWS raw gridpoint endpoint.
    """
    grid = await get_grid_coordinates(city)
    return f"{NWS_BASE_URL}/gridpoints/{grid['office']}/{grid['x']},{grid['y']}"


# ─── Forecast Fetchers ───


async def fetch_nws_forecast(city: str) -> list[WeatherData]:
    """Fetch NWS period forecast (12-hour blocks) for a city.

    The period forecast returns human-readable forecasts in Fahrenheit.
    We extract daytime periods and normalize them into WeatherData objects.

    Args:
        city: Kalshi city code (NYC, CHI, MIA, AUS).

    Returns:
        List of WeatherData objects, one per daytime forecast period.
        Typically returns 7 days of forecasts.

    Raises:
        FetchError: If the API call fails after retries.
        ParseError: If the response structure is unexpected.
    """
    url = await build_forecast_url(city)
    settings = get_settings()

    logger.info(
        "Fetching NWS period forecast",
        extra={"data": {"city": city, "url": url}},
    )

    raw_response = await fetch_with_retry(
        url,
        headers={"User-Agent": settings.nws_user_agent},
    )

    results = normalize_nws_forecast(city, raw_response)

    logger.info(
        "Parsed NWS period forecast",
        extra={
            "data": {
                "city": city,
                "periods_found": len(results),
                "highs": [r.forecast_high_f for r in results[:3]],
            }
        },
    )

    return results


async def fetch_nws_gridpoint(city: str) -> list[WeatherData]:
    """Fetch NWS raw gridpoint data for a city.

    The raw gridpoint endpoint returns machine-readable forecast data
    including maxTemperature, relativeHumidity, windSpeed, etc.
    CRITICAL: All temperatures are in CELSIUS and must be converted.

    Args:
        city: Kalshi city code (NYC, CHI, MIA, AUS).

    Returns:
        List of WeatherData objects parsed from the gridpoint data.

    Raises:
        FetchError: If the API call fails after retries.
        ParseError: If the response structure is unexpected.
    """
    url = await build_gridpoint_url(city)
    settings = get_settings()

    logger.info(
        "Fetching NWS gridpoint data",
        extra={"data": {"city": city, "url": url}},
    )

    raw_response = await fetch_with_retry(
        url,
        headers={"User-Agent": settings.nws_user_agent},
    )

    results = normalize_nws_gridpoint(city, raw_response)

    logger.info(
        "Parsed NWS gridpoint data",
        extra={
            "data": {
                "city": city,
                "forecasts_found": len(results),
                "highs": [r.forecast_high_f for r in results[:3]],
            }
        },
    )

    return results


# ─── CLI (Daily Climate Report) Fetcher ───

NWS_API_CLI_URL = "https://api.weather.gov/products/types/CLI/locations"


def build_cli_listing_url(city: str) -> str:
    """Build the NWS API URL to list CLI products for a city.

    Uses the api.weather.gov products endpoint which replaced the
    legacy forecast.weather.gov/product.php endpoint.

    Args:
        city: Kalshi city code (NYC, CHI, MIA, AUS).

    Returns:
        URL for the CLI product listing endpoint.

    Raises:
        KeyError: If city is not a valid city code.
    """
    config = STATION_CONFIGS[city]
    return f"{NWS_API_CLI_URL}/{config.cli_location}"


async def fetch_nws_cli(city: str) -> str:
    """Fetch the NWS CLI (Daily Climate Report) text for a city.

    Two-step fetch via api.weather.gov:
    1. List CLI products for the location to get the latest product ID
    2. Fetch the product JSON to extract productText

    The CLI report is published ~7-8 AM local time the morning after
    the settlement day. It contains the official observed high/low
    temperatures for the previous day.

    Args:
        city: Kalshi city code (NYC, CHI, MIA, AUS).

    Returns:
        Raw CLI report text string.

    Raises:
        KeyError: If city is not a valid city code.
        FetchError: If the fetch fails after retries.
    """
    listing_url = build_cli_listing_url(city)

    logger.info(
        "Fetching NWS CLI report",
        extra={"data": {"city": city, "url": listing_url}},
    )

    # Step 1: Get the latest CLI product ID
    listing = await fetch_with_retry(listing_url)
    products = listing.get("@graph", [])
    if not products:
        raise FetchError(f"No CLI products found for {city} at {listing_url}")

    product_id = products[0].get("id")
    if not product_id:
        raise FetchError(f"No product ID in CLI listing for {city}")

    # Step 2: Fetch the product JSON and extract productText
    product_url = f"https://api.weather.gov/products/{product_id}"
    product_data = await fetch_with_retry(product_url)
    text = product_data.get("productText", "")

    if not text:
        raise FetchError(f"Empty productText in CLI product {product_id} for {city}")

    logger.info(
        "Fetched NWS CLI report",
        extra={"data": {"city": city, "product_id": product_id, "text_length": len(text)}},
    )

    return text


async def fetch_all_nws_cli(city: str, max_products: int = 10) -> list[str]:
    """Fetch multiple recent NWS CLI reports for a city.

    Used for catch-up settlement when multiple days of reports were missed.
    Fetches up to max_products from the listing and returns their text.

    Args:
        city: Kalshi city code (NYC, CHI, MIA, AUS).
        max_products: Maximum number of products to fetch.

    Returns:
        List of raw CLI report text strings (newest first).

    Raises:
        KeyError: If city is not a valid city code.
        FetchError: If the listing fetch fails.
    """
    listing_url = build_cli_listing_url(city)
    listing = await fetch_with_retry(listing_url)
    products = listing.get("@graph", [])[:max_products]

    results: list[str] = []
    for product in products:
        product_id = product.get("id")
        if not product_id:
            continue
        try:
            product_url = f"https://api.weather.gov/products/{product_id}"
            product_data = await fetch_with_retry(product_url)
            text = product_data.get("productText", "")
            if text:
                results.append(text)
        except FetchError:
            logger.warning(
                "Failed to fetch CLI product",
                extra={"data": {"city": city, "product_id": product_id}},
            )
    return results

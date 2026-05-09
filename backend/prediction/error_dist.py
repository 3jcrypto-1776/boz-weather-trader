"""Historical forecast error distribution analysis.

Compares past NWS forecasts to actual NWS CLI settlement data to build
error distributions per city and season. Falls back to hardcoded estimates
when insufficient historical data is available (the "bootstrap problem").

Usage:
    from backend.prediction.error_dist import calculate_error_std, get_season

    error_std = await calculate_error_std("NYC", month=2, db_session=db)
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.logging import get_logger
from backend.common.models import Settlement, WeatherForecast

logger = get_logger("MODEL")

# Multiplier applied to the returned std to account for the gap between
# raw NWS single-source forecast error (what we measure) and the spread of
# the full blended pipeline output vs actuals (what brackets.py actually
# needs). Calibration data (Phase 1, v1.9.5) showed the model was
# systematically overconfident in the 0.3–0.9 probability range — widening
# the std shifts probability mass out of those buckets and onto the tails.
ERROR_STD_INFLATION_FACTOR = 1.4

# Fallback error standard deviations (used when insufficient historical data).
# These are conservative estimates based on typical NWS forecast accuracy.
# Values are in degrees Fahrenheit.
FALLBACK_ERROR_STD: dict[str, dict[str, float]] = {
    "NYC": {"winter": 3.0, "spring": 2.5, "summer": 1.8, "fall": 2.3},
    "CHI": {"winter": 3.5, "spring": 3.0, "summer": 2.0, "fall": 2.5},
    "MIA": {"winter": 1.5, "spring": 1.8, "summer": 2.0, "fall": 1.8},
    "AUS": {"winter": 2.5, "spring": 2.8, "summer": 2.0, "fall": 2.3},
}

# Season-to-months mapping for filtering historical data.
_SEASON_MONTHS: dict[str, tuple[int, ...]] = {
    "winter": (12, 1, 2),
    "spring": (3, 4, 5),
    "summer": (6, 7, 8),
    "fall": (9, 10, 11),
}


def get_season(month: int) -> str:
    """Get season from month number.

    Args:
        month: Month number (1-12).

    Returns:
        One of "winter", "spring", "summer", "fall".
    """
    if month in (12, 1, 2):
        return "winter"
    elif month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    else:
        return "fall"


async def calculate_error_std(
    city: str,
    month: int,
    db_session: AsyncSession,
    min_samples: int = 30,
) -> float:
    """Calculate historical forecast error standard deviation for a city/season.

    Compares past NWS forecasts to actual NWS CLI settlements for the same
    city and season. If insufficient data (<min_samples), falls back to
    hardcoded conservative estimates.

    Args:
        city: City code ("NYC", "CHI", "MIA", "AUS").
        month: Month number (1-12) to determine season.
        db_session: SQLAlchemy async session.
        min_samples: Minimum historical data points needed.

    Returns:
        Standard deviation of forecast errors in degrees Fahrenheit.
        Always returns a positive float.
    """
    season = get_season(month)
    season_months = _SEASON_MONTHS[season]

    try:
        # Query historical forecasts vs settlements for this city and season.
        # Join WeatherForecast with Settlement on (city, forecast_date == settlement_date).
        # Filter to same season months using extract().
        stmt = (
            select(
                WeatherForecast.forecast_high_f,
                Settlement.actual_high_f,
            )
            .join(
                Settlement,
                (WeatherForecast.city == Settlement.city)
                & (WeatherForecast.forecast_date == Settlement.settlement_date),
            )
            .where(
                WeatherForecast.city == city,
                WeatherForecast.source == "NWS",
                Settlement.actual_high_f.isnot(None),
                extract("month", WeatherForecast.forecast_date).in_(season_months),
            )
        )

        result = await db_session.execute(stmt)
        rows = result.all()

        # Calculate forecast errors (actual - predicted) for each pair.
        errors: list[float] = [actual_high - forecast_high for forecast_high, actual_high in rows]

        if len(errors) >= min_samples:
            raw_std = float(np.std(errors, ddof=1))  # sample std dev
            error_std = raw_std * ERROR_STD_INFLATION_FACTOR
            logger.info(
                "Calculated historical error std",
                extra={
                    "data": {
                        "city": city,
                        "season": season,
                        "raw_std_f": round(raw_std, 2),
                        "std_f": round(error_std, 2),
                        "inflation_factor": ERROR_STD_INFLATION_FACTOR,
                        "sample_count": len(errors),
                    }
                },
            )
            return error_std

        logger.info(
            "Insufficient historical data for error std",
            extra={
                "data": {
                    "city": city,
                    "season": season,
                    "sample_count": len(errors),
                    "min_required": min_samples,
                }
            },
        )

    except Exception as e:
        logger.warning(
            "Error querying historical data, using fallback",
            extra={
                "data": {
                    "city": city,
                    "season": season,
                    "error": str(e),
                }
            },
        )

    # Fall back to hardcoded conservative estimates.
    raw_fallback = FALLBACK_ERROR_STD.get(city, {}).get(season, 2.5)
    fallback = raw_fallback * ERROR_STD_INFLATION_FACTOR
    logger.info(
        "Using fallback error std",
        extra={
            "data": {
                "city": city,
                "season": season,
                "raw_std_f": raw_fallback,
                "std_f": round(fallback, 2),
                "inflation_factor": ERROR_STD_INFLATION_FACTOR,
                "reason": "insufficient_data",
            }
        },
    )
    return fallback

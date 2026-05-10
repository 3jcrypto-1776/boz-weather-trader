"""Historical forecast error distribution analysis.

Compares past full-pipeline predictions to actual NWS CLI settlement
data to build error distributions per city and season. The std measured
here describes the spread of ``Prediction.ensemble_mean_f`` (the blended
ensemble + ML + bias-corrected output) versus realized highs — i.e. the
actual variance the bracket CDF needs to model.

Falls back to hardcoded estimates when insufficient historical data is
available (the "bootstrap problem", first ~30 days of operation).

Usage:
    from backend.prediction.error_dist import calculate_error_std, get_season

    error_std = await calculate_error_std("NYC", month=2, db_session=db)
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import cast, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Date

from backend.common.logging import get_logger
from backend.common.models import Prediction, Settlement

logger = get_logger("MODEL")

# Fallback error standard deviations (used when insufficient historical data).
# These are conservative estimates — the v1.9.7 pipeline uses Student's t in
# brackets.py with df=10, which provides heavier tails than Normal at the
# same scale, so these values do not need to be inflated.
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
    """Calculate historical full-pipeline error standard deviation.

    Joins ``Prediction.ensemble_mean_f`` (the deployed pipeline output —
    ensemble + ML + bias correction) with ``Settlement.actual_high_f`` per
    day for the given city and season. Multiple predictions per day are
    averaged to one (predicted, actual) pair before computing the std,
    matching the pattern used by ``bias_correction.calculate_rolling_bias``.

    If insufficient data (<min_samples), falls back to hardcoded conservative
    estimates from ``FALLBACK_ERROR_STD``.

    Args:
        city: City code ("NYC", "CHI", "MIA", "AUS").
        month: Month number (1-12) to determine season.
        db_session: SQLAlchemy async session.
        min_samples: Minimum day-pairs needed before using calculated std.

    Returns:
        Standard deviation of full-pipeline forecast errors in °F.
        Always returns a positive float.
    """
    season = get_season(month)
    season_months = _SEASON_MONTHS[season]

    try:
        # Subquery: average ensemble_mean_f per day (one row per date).
        daily_pred = (
            select(
                cast(Prediction.prediction_date, Date).label("pred_date"),
                func.avg(Prediction.ensemble_mean_f).label("avg_predicted"),
            )
            .where(
                Prediction.city == city,
                extract("month", Prediction.prediction_date).in_(season_months),
            )
            .group_by(cast(Prediction.prediction_date, Date))
            .subquery("daily_pred")
        )

        # Join daily averages with settlements to get (predicted, actual) pairs.
        stmt = (
            select(
                daily_pred.c.avg_predicted,
                Settlement.actual_high_f,
            )
            .join(
                Settlement,
                (cast(Settlement.settlement_date, Date) == daily_pred.c.pred_date)
                & (Settlement.city == city),
            )
            .where(Settlement.actual_high_f.isnot(None))
        )

        result = await db_session.execute(stmt)
        rows = result.all()

        # Calculate full-pipeline forecast errors (actual - predicted).
        errors: list[float] = [float(actual_high - predicted) for predicted, actual_high in rows]

        if len(errors) >= min_samples:
            error_std = float(np.std(errors, ddof=1))  # sample std dev
            logger.info(
                "Calculated full-pipeline error std",
                extra={
                    "data": {
                        "city": city,
                        "season": season,
                        "std_f": round(error_std, 2),
                        "sample_count": len(errors),
                    }
                },
            )
            return max(error_std, 0.5)  # floor to avoid degenerate distributions

        logger.info(
            "Insufficient pipeline history for error std",
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
            "Error querying pipeline history, using fallback",
            extra={
                "data": {
                    "city": city,
                    "season": season,
                    "error": str(e),
                }
            },
        )

    # Fall back to hardcoded conservative estimates.
    fallback = FALLBACK_ERROR_STD.get(city, {}).get(season, 2.5)
    logger.info(
        "Using fallback error std",
        extra={
            "data": {
                "city": city,
                "season": season,
                "std_f": fallback,
                "reason": "insufficient_data",
            }
        },
    )
    return fallback

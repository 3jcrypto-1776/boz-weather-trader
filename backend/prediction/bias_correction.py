"""Rolling bias correction for ensemble temperature predictions.

Compares recent ensemble predictions to actual settlement temperatures
to detect and correct systematic forecast bias (e.g., consistently
predicting too cold or too warm). The correction is a rolling average
of recent errors that self-adjusts as model accuracy changes.

Usage:
    from backend.prediction.bias_correction import calculate_rolling_bias

    bias = await calculate_rolling_bias("NYC", target_date, db_session)
    corrected_temp = ensemble_temp + bias
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Date

from backend.common.logging import get_logger
from backend.common.models import Prediction, Settlement

logger = get_logger("MODEL")


async def calculate_rolling_bias(
    city: str,
    target_date: date,
    db_session: AsyncSession,
    lookback_days: int = 14,
    min_samples: int = 5,
) -> float:
    """Calculate rolling bias correction for a city's ensemble predictions.

    Compares recent daily average ensemble predictions to actual settlement
    temperatures over the last ``lookback_days`` days. Returns the mean
    error (actual - predicted) which should be ADDED to the ensemble temp
    to correct for systematic bias.

    The correction is self-balancing:
      - Positive return → model has been too cold → add to temp
      - Negative return → model has been too hot → subtract from temp
      - Zero return → model is accurate or insufficient data

    Args:
        city: City code ("NYC", "CHI", "MIA", "AUS").
        target_date: The date we are predicting for (used to compute lookback window).
        db_session: SQLAlchemy async session.
        lookback_days: Number of days to look back for error calculation.
        min_samples: Minimum number of day-pairs needed to compute a correction.

    Returns:
        Bias correction in degrees Fahrenheit to ADD to the ensemble temp.
        Returns 0.0 when insufficient data or on any error.
    """
    cutoff_date = target_date - timedelta(days=lookback_days)

    try:
        # Subquery: get average ensemble_mean_f per day for this city.
        # Multiple predictions per day (one per 15-min cycle) are averaged.
        daily_pred = (
            select(
                cast(Prediction.prediction_date, Date).label("pred_date"),
                func.avg(Prediction.ensemble_mean_f).label("avg_predicted"),
            )
            .where(
                Prediction.city == city,
                cast(Prediction.prediction_date, Date) >= cutoff_date,
                cast(Prediction.prediction_date, Date) < target_date,
            )
            .group_by(cast(Prediction.prediction_date, Date))
            .subquery("daily_pred")
        )

        # Join with settlements to get (avg_predicted, actual) pairs per day.
        stmt = select(
            daily_pred.c.avg_predicted,
            Settlement.actual_high_f,
        ).join(
            Settlement,
            (cast(Settlement.settlement_date, Date) == daily_pred.c.pred_date)
            & (Settlement.city == city),
        )

        result = await db_session.execute(stmt)
        rows = result.all()

        if len(rows) < min_samples:
            logger.debug(
                "Insufficient data for bias correction",
                extra={
                    "data": {
                        "city": city,
                        "date": str(target_date),
                        "sample_count": len(rows),
                        "min_required": min_samples,
                    }
                },
            )
            return 0.0

        # Calculate mean error: actual - predicted.
        # Positive = model was too cold, negative = model was too hot.
        errors = [actual - predicted for predicted, actual in rows]
        bias = sum(errors) / len(errors)

        logger.info(
            "Rolling bias calculated",
            extra={
                "data": {
                    "city": city,
                    "date": str(target_date),
                    "bias_f": round(bias, 2),
                    "sample_days": len(rows),
                    "lookback_days": lookback_days,
                }
            },
        )

        return float(bias)

    except Exception as e:
        logger.warning(
            "Error calculating rolling bias, skipping correction",
            extra={
                "data": {
                    "city": city,
                    "date": str(target_date),
                    "error": str(e),
                }
            },
        )
        return 0.0

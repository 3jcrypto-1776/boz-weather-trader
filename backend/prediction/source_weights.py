"""Source weight management — load/save/compute weather source ensemble weights.

Persists dynamically computed source weights to a JSON file alongside the ML
model weights. The prediction pipeline reads these on startup and uses them
instead of the hardcoded DEFAULT_MODEL_WEIGHTS when available.

Source weights are computed from forecast accuracy data using the same
inverse-RMSE formula used for ML model weights.

Usage:
    from backend.prediction.source_weights import (
        load_source_weights, save_source_weights, compute_source_weights_from_accuracy,
    )

    weights = load_source_weights("models")
    new_weights = await compute_source_weights_from_accuracy(db_session)
    save_source_weights(new_weights, "models")
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.logging import get_logger
from backend.prediction.ensemble import DEFAULT_MODEL_WEIGHTS

logger = get_logger("MODEL")

SOURCE_WEIGHTS_FILENAME = "source_weights.json"

# Minimum RMSE samples per source to include in weight calculation
_MIN_SAMPLES_PER_SOURCE = 5


def load_source_weights(model_dir: str = "models") -> dict[str, float] | None:
    """Load saved source weights from disk.

    Returns:
        Dict mapping source name to weight (sums to ~1.0), or None if no file exists
        or the file is corrupt.
    """
    path = Path(model_dir) / SOURCE_WEIGHTS_FILENAME
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        weights = data.get("weights")
        if isinstance(weights, dict) and len(weights) > 0:
            return weights
        return None
    except Exception:
        logger.warning(
            "Failed to load source weights — using defaults",
            extra={"data": {"path": str(path)}},
        )
        return None


def save_source_weights(
    weights: dict[str, float],
    model_dir: str = "models",
) -> None:
    """Save source weights to disk as JSON.

    Args:
        weights: Dict mapping source name to weight.
        model_dir: Directory to save in (alongside ML model files).
    """
    from datetime import UTC, datetime

    path = Path(model_dir) / SOURCE_WEIGHTS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "weights": weights,
        "computed_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info(
        "Source weights saved",
        extra={"data": {"weights": weights, "path": str(path)}},
    )


async def compute_source_weights_from_accuracy(
    session: AsyncSession,
    lookback_days: int = 90,
) -> dict[str, float]:
    """Compute source weights from recent forecast accuracy using inverse-RMSE.

    Queries per-source accuracy across all 4 cities, averages RMSE per source,
    then applies inverse-RMSE weighting: weight_i = (1/rmse_i) / sum(1/rmse_j).

    Sources with fewer than _MIN_SAMPLES_PER_SOURCE data points are excluded.

    Args:
        session: SQLAlchemy async session.
        lookback_days: Days of historical data to use.

    Returns:
        Dict mapping source name to weight (sums to ~1.0).
        Returns DEFAULT_MODEL_WEIGHTS if insufficient data.
    """
    from backend.prediction.accuracy import get_source_accuracy

    cities = ["NYC", "CHI", "MIA", "AUS"]

    # Collect RMSE per source across all cities
    source_rmse_accum: dict[str, list[float]] = {}
    source_samples: dict[str, int] = {}

    for city in cities:
        try:
            sources = await get_source_accuracy(city, session, lookback_days)
            for src in sources:
                if src.sample_count >= _MIN_SAMPLES_PER_SOURCE and src.rmse_f > 0:
                    source_rmse_accum.setdefault(src.source, []).append(src.rmse_f)
                    source_samples[src.source] = source_samples.get(src.source, 0) + (
                        src.sample_count
                    )
        except Exception:
            logger.warning(
                "Failed to get source accuracy for city",
                extra={"data": {"city": city}},
            )
            continue

    if not source_rmse_accum:
        logger.info(
            "Insufficient accuracy data for source weight computation — using defaults"
        )
        return dict(DEFAULT_MODEL_WEIGHTS)

    # Average RMSE across cities for each source
    avg_rmse: dict[str, float] = {}
    for source, rmse_list in source_rmse_accum.items():
        avg_rmse[source] = sum(rmse_list) / len(rmse_list)

    # Inverse-RMSE weighting (same formula as ML model weights)
    inv_scores: dict[str, float] = {}
    for source, rmse in avg_rmse.items():
        if rmse > 0:
            inv_scores[source] = 1.0 / rmse
        else:
            inv_scores[source] = 100.0  # Perfect model gets very high score

    total_inv = sum(inv_scores.values())
    if total_inv == 0 or math.isnan(total_inv):
        logger.warning("Inverse-RMSE total is zero or NaN — using defaults")
        return dict(DEFAULT_MODEL_WEIGHTS)

    weights = {src: round(score / total_inv, 4) for src, score in inv_scores.items()}

    logger.info(
        "Source weights computed from accuracy",
        extra={
            "data": {
                "weights": weights,
                "avg_rmse": {k: round(v, 2) for k, v in avg_rmse.items()},
                "sources": len(weights),
            }
        },
    )

    return weights

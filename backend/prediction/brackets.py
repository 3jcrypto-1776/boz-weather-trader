"""Bracket probability calculator using scipy CDF.

Given an ensemble forecast and error distribution, calculates the probability
of the actual temperature landing in each Kalshi bracket using a Student's
t-distribution CDF approach. The heavier tails (vs Normal) better model the
empirical distribution of weather forecast residuals, which exhibit more
extreme misses than a Normal would predict.

Usage:
    from backend.prediction.brackets import calculate_bracket_probabilities

    probs = calculate_bracket_probabilities(
        ensemble_forecast_f=54.05,
        error_std_f=2.1,
        brackets=kalshi_brackets,
    )
"""

from __future__ import annotations

from scipy import stats

from backend.common.logging import get_logger
from backend.common.schemas import BracketProbability

logger = get_logger("MODEL")

# Default degrees of freedom for the Student's t-distribution. df=10 gives
# moderately heavier tails than Normal (~2.3% mass beyond ±2σ vs ~2.3% for
# Normal but with much higher mass beyond ±3σ), which addresses the
# systematic over-confidence in the 0.7+ probability buckets observed in
# v1.9.5/v1.9.6 calibration data. Higher df converges to Normal.
DEFAULT_DF = 10


def calculate_bracket_probabilities(
    ensemble_forecast_f: float,
    error_std_f: float,
    brackets: list[dict],
    df: int = DEFAULT_DF,
) -> list[BracketProbability]:
    """Calculate probability of temperature landing in each bracket.

    Uses a Student's t-distribution centered on the ensemble forecast,
    with scale from historical forecast errors. The t-distribution's
    heavier tails better model the actual residual distribution of
    blended ensemble + ML weather predictions, which have more extreme
    misses than Normal would predict.

    The CDF approach:
    - Bottom bracket (lower_bound_f is None): P(temp < upper).
    - Top bracket (upper_bound_f is None): P(temp >= lower).
    - Middle brackets: CDF(upper) - CDF(lower).

    After CDF calculation, probabilities are normalized to ensure they
    sum to exactly 1.0 (handles floating-point drift).

    Args:
        ensemble_forecast_f: Weighted ensemble temperature forecast (Fahrenheit).
        error_std_f: Standard deviation of historical forecast errors for this
            city/season. Must be > 0. Used as the t-distribution's scale.
        brackets: List of bracket definitions from Kalshi (typically 6 brackets).
            Each dict must have keys: "lower_bound_f" (float|None),
            "upper_bound_f" (float|None), "label" (str).
        df: Degrees of freedom for the t-distribution. Lower = heavier tails.
            Defaults to ``DEFAULT_DF`` (10) — calibrated for weather residuals.

    Returns:
        List of BracketProbability objects with probabilities summing to 1.0.

    Raises:
        ValueError: If error_std_f <= 0, df <= 0, or brackets list is empty.
    """
    if error_std_f <= 0:
        msg = f"error_std_f must be positive, got {error_std_f}"
        raise ValueError(msg)
    if df <= 0:
        msg = f"df must be positive, got {df}"
        raise ValueError(msg)
    if not brackets:
        raise ValueError("Brackets list is empty")

    dist = stats.t(df=df, loc=ensemble_forecast_f, scale=error_std_f)
    results: list[BracketProbability] = []

    for bracket in brackets:
        lower = bracket.get("lower_bound_f")
        upper = bracket.get("upper_bound_f")

        if lower is None and upper is not None:
            # Bottom edge bracket: P(temp < upper)
            prob = dist.cdf(upper)
        elif upper is None and lower is not None:
            # Top edge bracket: P(temp >= lower)
            prob = 1.0 - dist.cdf(lower)
        elif lower is not None and upper is not None:
            # Middle bracket: P(lower <= temp < upper)
            prob = dist.cdf(upper) - dist.cdf(lower)
        else:
            # Both bounds are None -- should never happen with valid brackets.
            prob = 0.0

        results.append(
            BracketProbability(
                bracket_label=bracket["label"],
                lower_bound_f=lower,
                upper_bound_f=upper,
                probability=max(0.0, min(1.0, prob)),  # clamp to [0, 1]
            )
        )

    # Normalize to ensure sum == 1.0 (handles floating-point drift).
    total = sum(r.probability for r in results)
    if total > 0:
        for r in results:
            r.probability = r.probability / total

    logger.info(
        "Bracket probabilities calculated",
        extra={
            "data": {
                "ensemble_f": round(ensemble_forecast_f, 1),
                "error_std_f": round(error_std_f, 2),
                "df": df,
                "bracket_count": len(results),
                "probabilities": [round(r.probability, 4) for r in results],
                "sum_check": round(sum(r.probability for r in results), 6),
            }
        },
    )

    return results

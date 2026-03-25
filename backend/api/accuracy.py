"""Forecast accuracy endpoints.

Provides per-source forecast accuracy metrics, calibration reports,
error trend data, and model edge analysis for the analytics dashboard.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.response_schemas import (
    CalibrationReport,
    ForecastErrorTrend,
    ModelEdgeBucket,
    ModelEdgeReport,
    SourceAccuracy,
)
from backend.common.database import get_db
from backend.common.logging import get_logger
from backend.common.models import Trade, TradeStatus, User
from backend.prediction.accuracy import get_forecast_error_trend, get_source_accuracy
from backend.prediction.calibration import check_calibration

logger = get_logger("API")

router = APIRouter()


@router.get("/sources", response_model=list[SourceAccuracy])
async def get_accuracy_sources(
    city: str = Query(default="NYC", description="City code"),
    lookback_days: int = Query(default=90, ge=1, le=365, description="Lookback period in days"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SourceAccuracy]:
    """Get per-source forecast accuracy metrics (MAE, RMSE, bias).

    Compares each weather source's forecast_high_f against actual settlement
    temperatures over the lookback period.

    Args:
        city: City code ("NYC", "CHI", "MIA", "AUS").
        lookback_days: Number of days to look back.
        user: Authenticated user.
        db: Async database session.

    Returns:
        List of SourceAccuracy, one per weather source with data.
    """
    return await get_source_accuracy(city, db, lookback_days=lookback_days)


@router.get("/calibration", response_model=CalibrationReport)
async def get_calibration(
    city: str = Query(default="NYC", description="City code"),
    lookback_days: int = Query(default=90, ge=1, le=365, description="Lookback period in days"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalibrationReport:
    """Get calibration report with Brier score and calibration buckets.

    Checks how well-calibrated bracket probability predictions have been
    by comparing predicted probabilities to actual outcomes.

    Args:
        city: City code ("NYC", "CHI", "MIA", "AUS").
        lookback_days: Number of days to look back.
        user: Authenticated user.
        db: Async database session.

    Returns:
        CalibrationReport with Brier score and calibration bucket data.
    """
    return await check_calibration(city, db, lookback_days=lookback_days)


@router.get("/trends", response_model=ForecastErrorTrend)
async def get_accuracy_trends(
    city: str = Query(default="NYC", description="City code"),
    source: str = Query(default="NWS", description="Weather source name"),
    lookback_days: int = Query(default=90, ge=1, le=365, description="Lookback period in days"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ForecastErrorTrend:
    """Get forecast error trend data for charting.

    Returns individual (date, error) points and a 7-day rolling MAE
    for a specific city and weather source.

    Args:
        city: City code ("NYC", "CHI", "MIA", "AUS").
        source: Weather source name (e.g., "NWS", "Open-Meteo:GFS").
        lookback_days: Number of days to look back.
        user: Authenticated user.
        db: Async database session.

    Returns:
        ForecastErrorTrend with data points and rolling MAE.
    """
    return await get_forecast_error_trend(city, source, db, lookback_days=lookback_days)


# ─── Model Edge ───


def _compute_edge_bucket(
    trades: list[tuple[float, float, int]],
) -> ModelEdgeBucket:
    """Compute a ModelEdgeBucket from a list of (model_prob, market_prob, actual) tuples.

    Args:
        trades: List of (model_probability, market_probability, actual_outcome) tuples.

    Returns:
        ModelEdgeBucket with Brier scores, edge, and verdict.
    """
    n = len(trades)
    if n < 10:
        return ModelEdgeBucket(
            model_brier=0.0,
            market_brier=0.0,
            edge=0.0,
            sample_count=n,
            verdict="Insufficient data",
        )

    model_brier = sum((mp - a) ** 2 for mp, _, a in trades) / n
    market_brier = sum((mkp - a) ** 2 for _, mkp, a in trades) / n
    edge = market_brier - model_brier

    if edge > 0.001:
        verdict = "Model outperforming"
    elif edge < -0.001:
        verdict = "Market outperforming"
    else:
        verdict = "Model outperforming"  # Tie goes to model

    return ModelEdgeBucket(
        model_brier=round(model_brier, 6),
        market_brier=round(market_brier, 6),
        edge=round(edge, 6),
        sample_count=n,
        verdict=verdict,
    )


@router.get("/edge", response_model=ModelEdgeReport)
async def get_model_edge(
    lookback_days: int = Query(default=90, ge=1, le=365, description="Lookback period in days"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelEdgeReport:
    """Compare model predictions vs market prices using Brier scores.

    For each settled trade, determines whether the bracket actually hit and
    computes Brier scores for both the model's predicted probability and the
    market-implied probability. A lower Brier score indicates better
    calibration. Positive edge means the model outperforms the market.

    Args:
        lookback_days: Number of days to look back.
        user: Authenticated user.
        db: Async database session.

    Returns:
        ModelEdgeReport with overall and per-side/city breakdowns.
    """
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=lookback_days)

    result = await db.execute(
        select(Trade).where(
            Trade.user_id == user.id,
            Trade.status.in_([TradeStatus.WON, TradeStatus.LOST]),
            Trade.settled_at >= cutoff,
        )
    )
    trades = list(result.scalars().all())

    # Build data tuples: (model_prob, market_prob, actual_outcome)
    all_tuples: list[tuple[float, float, int]] = []
    by_side: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    by_city: dict[str, list[tuple[float, float, int]]] = defaultdict(list)

    for trade in trades:
        # Determine actual outcome: did the bracket hit?
        status_str = trade.status.value if hasattr(trade.status, "value") else trade.status
        side = trade.side

        if (status_str == "WON" and side == "yes") or (status_str == "LOST" and side == "no"):
            actual = 1
        else:
            actual = 0

        model_prob = trade.model_probability
        market_prob = trade.market_probability

        entry = (model_prob, market_prob, actual)
        all_tuples.append(entry)
        by_side[side].append(entry)

        city = trade.city.value if hasattr(trade.city, "value") else trade.city
        by_city[city].append(entry)

    # Compute overall bucket
    overall = _compute_edge_bucket(all_tuples)

    # Compute per-side and per-city buckets
    side_buckets = {s: _compute_edge_bucket(tuples) for s, tuples in by_side.items()}
    city_buckets = {c: _compute_edge_bucket(tuples) for c, tuples in by_city.items()}

    # Compute edge_pct
    if overall.market_brier > 0 and overall.sample_count >= 10:
        edge_pct = f"{abs(overall.edge / overall.market_brier * 100):.0f}%"
    else:
        edge_pct = "0%"

    return ModelEdgeReport(
        model_brier=overall.model_brier,
        market_brier=overall.market_brier,
        edge=overall.edge,
        edge_pct=edge_pct,
        verdict=overall.verdict,
        sample_count=overall.sample_count,
        by_side=side_buckets,
        by_city=city_buckets,
    )

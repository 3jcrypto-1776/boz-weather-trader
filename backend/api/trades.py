"""Trade history endpoint with pagination, filters, and portfolio sync.

Provides paginated access to the user's trade history with optional
filtering by city and status, plus a sync endpoint to reconcile
with Kalshi's actual portfolio.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_kalshi_client, trade_to_record
from backend.api.response_schemas import TradesPage
from backend.common.database import get_db
from backend.common.logging import get_logger
from backend.common.models import Trade, User
from backend.common.schemas import CityCode, SyncResult
from backend.websocket.events import publish_event

logger = get_logger("API")

router = APIRouter()

TRADES_PER_PAGE = 20


@router.get("", response_model=TradesPage)
async def get_trades(
    city: CityCode | None = None,
    status: str | None = None,
    trade_date: date | None = None,
    page: int = 1,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TradesPage:
    """Fetch paginated trade history with optional filters.

    Args:
        city: Optional city code filter (NYC, CHI, MIA, AUS).
        status: Optional status filter (OPEN, WON, LOST, CANCELED).
        trade_date: Optional date filter (YYYY-MM-DD) for calendar drill-down.
        page: Page number (1-indexed, defaults to 1).
        user: The authenticated user.
        db: Async database session.

    Returns:
        TradesPage with the filtered/paginated trades, total count, and page.
    """
    # Base query filtered by user
    base_query = select(Trade).where(Trade.user_id == user.id)
    count_query = select(func.count(Trade.id)).where(Trade.user_id == user.id)

    # Apply optional filters
    if city is not None:
        base_query = base_query.where(Trade.city == city)
        count_query = count_query.where(Trade.city == city)

    if status is not None:
        base_query = base_query.where(Trade.status == status)
        count_query = count_query.where(Trade.status == status)

    if trade_date is not None:
        base_query = base_query.where(func.date(Trade.trade_date) == trade_date)
        count_query = count_query.where(func.date(Trade.trade_date) == trade_date)

    # Get total count
    total_result = await db.execute(count_query)
    total = int(total_result.scalar())

    # Apply ordering and pagination
    offset = (page - 1) * TRADES_PER_PAGE
    paginated_query = (
        base_query.order_by(Trade.created_at.desc()).offset(offset).limit(TRADES_PER_PAGE)
    )

    result = await db.execute(paginated_query)
    trades = [trade_to_record(t) for t in result.scalars().all()]

    logger.info(
        "Trades fetched",
        extra={
            "data": {
                "city": city,
                "status": status,
                "page": page,
                "returned": len(trades),
                "total": total,
            }
        },
    )

    return TradesPage(trades=trades, total=total, page=page)


@router.post("/sync", response_model=SyncResult)
async def sync_trades(
    user: User = Depends(get_current_user),
    kalshi_client=Depends(get_kalshi_client),
    db: AsyncSession = Depends(get_db),
) -> SyncResult:
    """Sync app trade records with actual Kalshi portfolio.

    Fetches all filled orders from Kalshi and creates Trade records
    for any orders not already tracked by the app.
    """
    from backend.trading.sync import sync_portfolio

    try:
        result = await sync_portfolio(kalshi_client, db, user.id)
    except Exception as exc:
        logger.error(
            "Portfolio sync failed",
            extra={"data": {"error": str(exc)}},
        )
        raise HTTPException(status_code=500, detail=f"Sync failed: {exc}") from exc

    if result.synced_count > 0:
        await publish_event("trade.synced", {"synced_count": result.synced_count})

    logger.info(
        "Portfolio sync via API",
        extra={
            "data": {
                "synced": result.synced_count,
                "skipped": result.skipped_count,
                "failed": result.failed_count,
            }
        },
    )

    return result


@router.post("/settle")
async def settle_trades_now(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger settlement for all OPEN trades with matching settlement data.

    Fetches fresh CLI reports for all cities, creates Settlement records,
    then settles any OPEN trades that have matching data. Useful for
    catching up on missed scheduled settlements.
    """
    from backend.common.models import Settlement, TradeStatus
    from backend.trading.postmortem import settle_trade
    from backend.weather.cli_parser import parse_cli_text
    from backend.weather.nws import fetch_all_nws_cli
    from backend.weather.stations import VALID_CITIES

    # Step 1: Fetch ALL available CLI reports and create Settlement records
    cli_fetched = 0
    for city in VALID_CITIES:
        try:
            cli_texts = await fetch_all_nws_cli(city)
            for cli_text in cli_texts:
                try:
                    report = parse_cli_text(cli_text)
                except Exception:
                    continue

                # Check for existing settlement
                existing = await db.execute(
                    select(Settlement).where(
                        Settlement.city == city,
                        Settlement.settlement_date == report.report_date,
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                settlement = Settlement(
                    city=city,
                    settlement_date=report.report_date,
                    actual_high_f=report.high_f,
                    actual_low_f=report.low_f,
                    source="NWS_CLI",
                    raw_data={"station": report.station, "raw_text": report.raw_text[:2000]},
                )
                db.add(settlement)
                cli_fetched += 1
        except Exception as exc:
            logger.warning(
                "CLI fetch failed during manual settle",
                extra={"data": {"city": city, "error": str(exc)}},
            )

    if cli_fetched > 0:
        await db.commit()

    # Step 2: Settle OPEN trades with matching settlement data
    open_trades_result = await db.execute(
        select(Trade).where(Trade.user_id == user.id, Trade.status == TradeStatus.OPEN)
    )

    settled_count = 0
    for trade in open_trades_result.scalars().all():
        settlement_result = await db.execute(
            select(Settlement).where(
                Settlement.city == trade.city,
                func.date(Settlement.settlement_date) == func.date(trade.trade_date),
            )
        )
        settlement = settlement_result.scalar_one_or_none()
        if settlement is None:
            continue

        await settle_trade(trade, settlement, db)
        settled_count += 1

    await db.commit()

    logger.info(
        "Manual settlement triggered",
        extra={"data": {"cli_fetched": cli_fetched, "settled": settled_count}},
    )

    return {"cli_fetched": cli_fetched, "settled_count": settled_count}


@router.post("/regenerate-postmortems")
async def regenerate_postmortems(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Regenerate post-mortem narratives for all settled trades.

    Re-runs the narrative generator with the updated rich format for
    all WON/LOST trades that have matching settlement data.
    """
    from backend.common.models import Settlement, TradeStatus, WeatherForecast
    from backend.trading.postmortem import generate_postmortem_narrative

    settled_result = await db.execute(
        select(Trade).where(
            Trade.user_id == user.id,
            Trade.status.in_([TradeStatus.WON, TradeStatus.LOST]),
        )
    )

    count = 0
    for trade in settled_result.scalars().all():
        # Find matching settlement
        settlement_result = await db.execute(
            select(Settlement).where(
                Settlement.city == trade.city,
                func.date(Settlement.settlement_date) == func.date(trade.trade_date),
            )
        )
        settlement = settlement_result.scalar_one_or_none()
        if settlement is None:
            continue

        # Fetch forecasts for this trade
        forecasts_result = await db.execute(
            select(WeatherForecast).where(
                WeatherForecast.city == trade.city,
                WeatherForecast.forecast_date == trade.trade_date,
            )
        )
        forecasts = list(forecasts_result.scalars().all())

        trade.postmortem_narrative = generate_postmortem_narrative(trade, settlement, forecasts)
        count += 1

    await db.commit()

    logger.info(
        "Regenerated post-mortem narratives",
        extra={"data": {"count": count}},
    )

    return {"regenerated_count": count}

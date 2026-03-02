"""Trade history endpoint with pagination, filters, and portfolio sync.

Provides paginated access to the user's trade history with optional
filtering by city and status, plus a sync endpoint to reconcile
with Kalshi's actual portfolio.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_kalshi_client, trade_to_record
from backend.api.response_schemas import TradesPage
from backend.common.database import get_db
from backend.common.logging import get_logger
from backend.common.models import Trade, TradeStatus, User
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
    per_page: int = TRADES_PER_PAGE,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TradesPage:
    """Fetch paginated trade history with optional filters.

    Args:
        city: Optional city code filter (NYC, CHI, MIA, AUS).
        status: Optional status filter (OPEN, RESTING, WON, LOST,
                ACTIVE=OPEN+RESTING, SETTLED=WON+LOST).
        trade_date: Optional date filter (YYYY-MM-DD) for calendar drill-down.
        page: Page number (1-indexed, defaults to 1).
        per_page: Results per page (1-200, defaults to 20).
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
        if status.upper() == "ACTIVE":
            # Pseudo-filter: active trades (OPEN + RESTING)
            active = [TradeStatus.OPEN, TradeStatus.RESTING]
            base_query = base_query.where(Trade.status.in_(active))
            count_query = count_query.where(Trade.status.in_(active))
        elif status.upper() == "SETTLED":
            # Pseudo-filter: settled trades (WON + LOST)
            settled = [TradeStatus.WON, TradeStatus.LOST]
            base_query = base_query.where(Trade.status.in_(settled))
            count_query = count_query.where(Trade.status.in_(settled))
        else:
            base_query = base_query.where(Trade.status == status)
            count_query = count_query.where(Trade.status == status)

    if trade_date is not None:
        base_query = base_query.where(func.date(Trade.trade_date) == trade_date)
        count_query = count_query.where(func.date(Trade.trade_date) == trade_date)

    # Get total count
    total_result = await db.execute(count_query)
    total = int(total_result.scalar())

    # Clamp per_page to safe range
    per_page = max(1, min(per_page, 200))

    # Apply ordering and pagination
    offset = (page - 1) * per_page
    paginated_query = base_query.order_by(Trade.created_at.desc()).offset(offset).limit(per_page)

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
    kalshi_client=Depends(get_kalshi_client),
    resettle: bool = Query(False, description="Reset all settled trades and re-settle"),
) -> dict:
    """Manually trigger settlement using Kalshi's authoritative market results.

    Fetches settlement data from Kalshi (which side won each market),
    then settles any OPEN trades whose ticker matches. NWS CLI data is
    fetched separately for display-only fields (actual temperature).

    If resettle=true, resets ALL WON/LOST trades back to OPEN first,
    then re-runs settlement from scratch.
    """
    from backend.common.models import Settlement, TradeStatus
    from backend.trading.postmortem import settle_from_kalshi
    from backend.weather.cli_parser import parse_cli_text
    from backend.weather.nws import fetch_all_nws_cli
    from backend.weather.stations import VALID_CITIES

    # Step 0 (optional): Reset settled trades back to OPEN for re-settlement
    reset_count = 0
    if resettle:
        settled_result = await db.execute(
            select(Trade).where(
                Trade.user_id == user.id,
                Trade.status.in_([TradeStatus.WON, TradeStatus.LOST]),
            )
        )
        for trade in settled_result.scalars().all():
            trade.status = TradeStatus.OPEN
            trade.settlement_temp_f = None
            trade.settlement_source = None
            trade.pnl_cents = None
            trade.fees_cents = None
            trade.settled_at = None
            trade.postmortem_narrative = None
            reset_count += 1
        if reset_count > 0:
            await db.commit()
        logger.info(
            "Re-settlement: reset trades to OPEN",
            extra={"data": {"reset_count": reset_count}},
        )

    # Step 1: Fetch Kalshi settlements (authoritative win/loss source)
    kalshi_settlements = await kalshi_client.get_settlements()
    ticker_results = {s.ticker: s.market_result for s in kalshi_settlements}

    # Step 2: Fetch NWS CLI reports for display-only temperature data
    cli_fetched = 0
    for city in VALID_CITIES:
        try:
            cli_texts = await fetch_all_nws_cli(city)
            for cli_text in cli_texts:
                try:
                    report = parse_cli_text(cli_text)
                except Exception:
                    continue

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

    # Step 3: Settle OPEN trades using Kalshi market results
    open_trades_result = await db.execute(
        select(Trade).where(Trade.user_id == user.id, Trade.status == TradeStatus.OPEN)
    )

    settled_count = 0
    for trade in open_trades_result.scalars().all():
        # Check if Kalshi has settled this market
        market_result = ticker_results.get(trade.market_ticker)
        if market_result is None:
            continue  # Market not settled on Kalshi yet

        # Optionally look up NWS temp for display
        nws_settlement = None
        settle_date = trade.market_date or trade.trade_date
        if settle_date is not None:
            nws_result = await db.execute(
                select(Settlement).where(
                    Settlement.city == trade.city,
                    func.date(Settlement.settlement_date) == func.date(settle_date),
                )
            )
            nws_settlement = nws_result.scalar_one_or_none()

        await settle_from_kalshi(trade, market_result, db, nws_settlement)
        settled_count += 1

    await db.commit()

    logger.info(
        "Manual settlement triggered",
        extra={
            "data": {
                "cli_fetched": cli_fetched,
                "kalshi_settlements": len(ticker_results),
                "settled": settled_count,
                "reset": reset_count,
            }
        },
    )

    return {
        "cli_fetched": cli_fetched,
        "kalshi_settlements": len(ticker_results),
        "settled_count": settled_count,
        "reset_count": reset_count,
    }


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

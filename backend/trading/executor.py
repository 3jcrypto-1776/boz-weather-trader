"""Trade execution orchestrator -- places orders on Kalshi and records them.

Handles the full lifecycle of executing a trade signal:
1. Build a validated OrderRequest from the TradeSignal
2. Place the order via KalshiClient (with 14-minute expiration)
3. Handle the response (filled, partial fill, resting, rejection)
4. Create a Trade ORM record in the database
5. Return a TradeRecord schema

CRITICAL: All prices are in CENTS (integers). The Trade ORM model stores
price_cents as an integer, NOT a float.

Usage:
    from backend.trading.executor import execute_trade

    trade_record = await execute_trade(
        signal=signal,
        kalshi_client=client,
        db=session,
        user_id="u123",
    )
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exceptions import InvalidOrderError
from backend.common.logging import get_logger
from backend.common.models import Trade, TradeStatus
from backend.common.schemas import TradeRecord, TradeSignal
from backend.kalshi.markets import parse_market_date_from_ticker
from backend.kalshi.models import OrderRequest

logger = get_logger("ORDER")
ET = ZoneInfo("America/New_York")

# Resting orders auto-expire after 14 minutes. This fits within the
# 15-minute Celery beat cycle, ensuring no overlap with the next cycle.
RESTING_EXPIRY_SECONDS = 14 * 60


async def execute_trade(
    signal: TradeSignal,
    kalshi_client: object,
    db: AsyncSession,
    user_id: str,
) -> TradeRecord:
    """Execute a trade on Kalshi and record it in the database.

    Steps:
    1. Build OrderRequest from the signal with 14-minute expiration
    2. Place order via kalshi_client.place_order()
    3. Handle response: check status, partial fills, resting
    4. Create Trade ORM record (OPEN for filled, RESTING for unfilled)
    5. Return TradeRecord schema

    Args:
        signal: The trade signal to execute.
        kalshi_client: An authenticated KalshiClient instance.
        db: Async database session.
        user_id: The user ID placing the trade.

    Returns:
        A TradeRecord representing the executed trade.

    Raises:
        InvalidOrderError: If the order is rejected by Kalshi.
        Exception: If the Kalshi API call fails for any reason.
    """
    # Build the order with auto-expiry
    expiration_ts = int(time.time()) + RESTING_EXPIRY_SECONDS

    order = OrderRequest(
        ticker=signal.market_ticker,
        action="buy",
        side=signal.side,
        type="limit",
        count=signal.quantity,
        yes_price=signal.price_cents,
        expiration_ts=expiration_ts,
    )

    logger.info(
        "Placing order",
        extra={
            "data": {
                "ticker": signal.market_ticker,
                "side": signal.side,
                "price_cents": signal.price_cents,
                "quantity": signal.quantity,
                "expiration_ts": expiration_ts,
            }
        },
    )

    # Place the order
    try:
        response = await kalshi_client.place_order(order)
    except Exception as exc:
        logger.error(
            "Order placement failed",
            extra={
                "data": {
                    "ticker": signal.market_ticker,
                    "error": str(exc),
                    "side": signal.side,
                    "price_cents": signal.price_cents,
                }
            },
        )
        raise

    # Extract order details from response
    order_id = response.order_id
    filled_count = response.count
    order_status = response.status

    # Calculate actual fill price per contract from Kalshi response.
    # taker_fill_cost is the total cost in cents for all filled contracts.
    # Falls back to signal limit price if fill cost not available (e.g., demo mode).
    taker_fill_cost = getattr(response, "taker_fill_cost", 0) or 0
    fill_price_cents = (
        taker_fill_cost // filled_count
        if taker_fill_cost > 0 and filled_count > 0
        else signal.price_cents
    )

    # For NO side, convert to actual NO cost.
    # In both paths above, fill_price_cents holds the YES-equivalent price:
    #   - taker_fill_cost path: Kalshi reports YES-equivalent total for NO buys
    #   - fallback path: signal.price_cents is the YES market price
    # Actual NO cost = 100 - YES price.
    # price_cents stores actual cost per contract for both sides:
    #   cost = price_cents * qty   (both YES and NO)
    if signal.side == "no":
        fill_price_cents = 100 - fill_price_cents

    # Check for cancellation
    if order_status == "canceled":
        logger.warning(
            "Order was canceled by exchange",
            extra={"data": {"order_id": order_id}},
        )
        raise InvalidOrderError(
            "Order canceled by exchange",
            context={
                "order_id": order_id,
                "ticker": signal.market_ticker,
            },
        )

    # Handle fully resting orders (no fills) — record as RESTING.
    # The order will auto-expire on Kalshi after 14 minutes. The next
    # trading cycle will sync the status via _sync_resting_orders().
    if order_status == "resting" and filled_count == 0:
        trade_id = str(uuid4())
        now = datetime.now(UTC).replace(tzinfo=None)
        market_date = parse_market_date_from_ticker(signal.market_ticker)

        trade = Trade(
            id=trade_id,
            user_id=user_id,
            kalshi_order_id=order_id,
            city=signal.city,
            trade_date=now,
            market_date=market_date,
            market_ticker=signal.market_ticker,
            bracket_label=signal.bracket,
            side=signal.side,
            price_cents=(100 - signal.price_cents) if signal.side == "no" else signal.price_cents,
            quantity=signal.quantity,  # Requested quantity (not filled yet)
            model_probability=signal.model_probability,
            blended_probability=signal.blended_probability,
            market_probability=signal.market_probability,
            ev_at_entry=signal.ev,
            confidence=signal.confidence,
            status=TradeStatus.RESTING,
            created_at=now,
        )

        db.add(trade)
        await db.flush()

        logger.info(
            "Order resting on book — recorded as RESTING",
            extra={
                "data": {
                    "trade_id": trade_id,
                    "order_id": order_id,
                    "ticker": signal.market_ticker,
                    "side": signal.side,
                    "price_cents": signal.price_cents,
                    "quantity": signal.quantity,
                    "expiration_ts": expiration_ts,
                }
            },
        )

        resting_price = (100 - signal.price_cents) if signal.side == "no" else signal.price_cents
        return TradeRecord(
            id=trade_id,
            kalshi_order_id=order_id,
            city=signal.city,
            date=now.date(),
            market_ticker=signal.market_ticker,
            bracket_label=signal.bracket,
            side=signal.side,
            price_cents=resting_price,
            quantity=signal.quantity,
            model_probability=signal.model_probability,
            market_probability=signal.market_probability,
            ev_at_entry=signal.ev,
            confidence=signal.confidence,
            status="RESTING",
            settlement_temp_f=None,
            settlement_source=None,
            pnl_cents=None,
            created_at=now,
            settled_at=None,
        )

    # Log partial fills (some filled, some still resting).
    # Only the filled portion is recorded as OPEN. The unfilled remainder
    # will auto-expire on Kalshi.
    if order_status == "resting" and filled_count > 0:
        logger.info(
            "Order partially filled, remainder resting (will auto-expire)",
            extra={
                "data": {
                    "order_id": order_id,
                    "ticker": signal.market_ticker,
                    "filled": filled_count,
                    "requested": signal.quantity,
                }
            },
        )

    # Record the trade in the database (filled portion)
    trade_id = str(uuid4())
    now = datetime.now(UTC).replace(tzinfo=None)

    # Extract the market event date from the ticker (e.g., KXHIGHAUS-26FEB23 → Feb 23)
    market_date = parse_market_date_from_ticker(signal.market_ticker)

    # Store Kalshi's actual taker_fees (charged at trade time, not settlement).
    # This is 0 for resting/maker orders and >0 for immediately matched orders.
    taker_fees = getattr(response, "taker_fees", 0) or 0

    trade = Trade(
        id=trade_id,
        user_id=user_id,
        kalshi_order_id=order_id,
        city=signal.city,
        trade_date=now,
        market_date=market_date,
        market_ticker=signal.market_ticker,
        bracket_label=signal.bracket,
        side=signal.side,
        price_cents=fill_price_cents,
        quantity=filled_count,
        model_probability=signal.model_probability,
        blended_probability=signal.blended_probability,
        market_probability=signal.market_probability,
        ev_at_entry=signal.ev,
        confidence=signal.confidence,
        status=TradeStatus.OPEN,
        fees_cents=taker_fees if taker_fees > 0 else None,
        created_at=now,
    )

    db.add(trade)
    await db.flush()

    logger.info(
        "Trade executed and recorded",
        extra={
            "data": {
                "trade_id": trade_id,
                "order_id": order_id,
                "city": signal.city,
                "bracket": signal.bracket,
                "side": signal.side,
                "limit_price_cents": signal.price_cents,
                "fill_price_cents": fill_price_cents,
                "quantity": filled_count,
                "ev": signal.ev,
            }
        },
    )

    return TradeRecord(
        id=trade_id,
        kalshi_order_id=order_id,
        city=signal.city,
        date=now.date(),
        market_ticker=signal.market_ticker,
        bracket_label=signal.bracket,
        side=signal.side,
        price_cents=fill_price_cents,
        quantity=filled_count,
        model_probability=signal.model_probability,
        market_probability=signal.market_probability,
        ev_at_entry=signal.ev,
        confidence=signal.confidence,
        status="OPEN",
        settlement_temp_f=None,
        settlement_source=None,
        pnl_cents=None,
        created_at=now,
        settled_at=None,
    )

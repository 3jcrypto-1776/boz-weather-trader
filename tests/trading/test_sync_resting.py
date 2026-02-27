"""Tests for _sync_resting_orders in the trading scheduler.

Verifies the resting order sync logic that runs at the start of each
trading cycle, transitioning RESTING trades to OPEN (filled), CANCELED
(expired), or leaving them unchanged (still resting).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.common.models import TradeStatus


def _make_mock_trade(
    trade_id: str = "t1",
    order_id: str = "order-1",
    side: str = "yes",
    price_cents: int = 22,
    quantity: int = 1,
) -> MagicMock:
    """Create a mock Trade ORM object with RESTING status."""
    trade = MagicMock()
    trade.id = trade_id
    trade.kalshi_order_id = order_id
    trade.side = side
    trade.price_cents = price_cents
    trade.quantity = quantity
    trade.status = TradeStatus.RESTING
    trade.fees_cents = None
    return trade


def _make_mock_order(
    order_id: str = "order-1",
    status: str = "resting",
    fill_count: int = 0,
    taker_fill_cost: int = 0,
    taker_fees: int = 0,
) -> MagicMock:
    """Create a mock OrderResponse from Kalshi."""
    order = MagicMock()
    order.order_id = order_id
    order.status = status
    order.fill_count = fill_count
    order.taker_fill_cost = taker_fill_cost
    order.taker_fees = taker_fees
    return order


class TestSyncRestingOrders:
    """Tests for _sync_resting_orders in scheduler.py."""

    @pytest.mark.asyncio
    async def test_no_resting_trades_returns_zero(self) -> None:
        """When there are no RESTING trades, returns 0."""
        from backend.trading.scheduler import _sync_resting_orders

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await _sync_resting_orders(mock_session, AsyncMock(), "user-1")
        assert result == 0

    @pytest.mark.asyncio
    async def test_filled_order_transitions_to_open(self) -> None:
        """When Kalshi order is executed, trade transitions RESTING → OPEN."""
        from backend.trading.scheduler import _sync_resting_orders

        trade = _make_mock_trade(order_id="order-1", price_cents=22)
        kalshi_order = _make_mock_order(
            order_id="order-1",
            status="executed",
            fill_count=1,
            taker_fill_cost=20,
            taker_fees=1,
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]
        mock_session.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_client.get_orders.return_value = [kalshi_order]

        result = await _sync_resting_orders(mock_session, mock_client, "user-1")

        assert result == 1
        assert trade.status == TradeStatus.OPEN
        assert trade.price_cents == 20  # Updated to fill price
        assert trade.quantity == 1
        assert trade.fees_cents == 1

    @pytest.mark.asyncio
    async def test_filled_no_side_converts_price(self) -> None:
        """For NO side fills, price is converted to YES-equivalent."""
        from backend.trading.scheduler import _sync_resting_orders

        trade = _make_mock_trade(order_id="order-1", side="no", price_cents=40)
        kalshi_order = _make_mock_order(
            order_id="order-1",
            status="executed",
            fill_count=1,
            taker_fill_cost=59,
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]
        mock_session.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_client.get_orders.return_value = [kalshi_order]

        await _sync_resting_orders(mock_session, mock_client, "user-1")

        # NO side: YES-equivalent = 100 - 59 = 41
        assert trade.price_cents == 41

    @pytest.mark.asyncio
    async def test_canceled_order_transitions_to_canceled(self) -> None:
        """When Kalshi order is canceled, trade transitions RESTING → CANCELED."""
        from backend.trading.scheduler import _sync_resting_orders

        trade = _make_mock_trade(order_id="order-1")
        kalshi_order = _make_mock_order(order_id="order-1", status="canceled")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]
        mock_session.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_client.get_orders.return_value = [kalshi_order]

        result = await _sync_resting_orders(mock_session, mock_client, "user-1")

        assert result == 1
        assert trade.status == TradeStatus.CANCELED

    @pytest.mark.asyncio
    async def test_order_not_found_transitions_to_canceled(self) -> None:
        """When order is not found on Kalshi, trade transitions to CANCELED."""
        from backend.trading.scheduler import _sync_resting_orders

        trade = _make_mock_trade(order_id="order-1")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]
        mock_session.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_client.get_orders.return_value = []  # Order not found

        result = await _sync_resting_orders(mock_session, mock_client, "user-1")

        assert result == 1
        assert trade.status == TradeStatus.CANCELED

    @pytest.mark.asyncio
    async def test_still_resting_no_change(self) -> None:
        """When Kalshi order is still resting, trade stays RESTING."""
        from backend.trading.scheduler import _sync_resting_orders

        trade = _make_mock_trade(order_id="order-1")
        kalshi_order = _make_mock_order(order_id="order-1", status="resting")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]
        mock_session.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_client.get_orders.return_value = [kalshi_order]

        result = await _sync_resting_orders(mock_session, mock_client, "user-1")

        assert result == 0
        assert trade.status == TradeStatus.RESTING

    @pytest.mark.asyncio
    async def test_multiple_trades_mixed_outcomes(self) -> None:
        """Multiple resting trades can have different sync outcomes."""
        from backend.trading.scheduler import _sync_resting_orders

        trade1 = _make_mock_trade(trade_id="t1", order_id="order-1")
        trade2 = _make_mock_trade(trade_id="t2", order_id="order-2")
        trade3 = _make_mock_trade(trade_id="t3", order_id="order-3")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade1, trade2, trade3]
        mock_session.execute.return_value = mock_result

        # order-1: filled, order-2: still resting, order-3: not found (expired)
        mock_client = AsyncMock()
        mock_client.get_orders.return_value = [
            _make_mock_order("order-1", status="executed", fill_count=1, taker_fill_cost=20),
            _make_mock_order("order-2", status="resting"),
        ]

        result = await _sync_resting_orders(mock_session, mock_client, "user-1")

        assert result == 2  # t1 (filled) + t3 (expired)
        assert trade1.status == TradeStatus.OPEN
        assert trade2.status == TradeStatus.RESTING
        assert trade3.status == TradeStatus.CANCELED

    @pytest.mark.asyncio
    async def test_kalshi_api_failure_returns_zero(self) -> None:
        """When get_orders fails, returns 0 gracefully."""
        from backend.trading.scheduler import _sync_resting_orders

        trade = _make_mock_trade(order_id="order-1")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [trade]
        mock_session.execute.return_value = mock_result

        mock_client = AsyncMock()
        mock_client.get_orders.side_effect = ConnectionError("API down")

        result = await _sync_resting_orders(mock_session, mock_client, "user-1")

        assert result == 0
        # Trade should remain unchanged
        assert trade.status == TradeStatus.RESTING

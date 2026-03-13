"""Tests for orderbook-based pricing fallback in scheduler.

Tests cover:
- best_yes_price_from_orderbook() helper function
- _fetch_market_prices() orderbook fallback path
- ORDERBOOK_FALLBACK_TOTAL Prometheus counter
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from backend.trading.scheduler import best_yes_price_from_orderbook

# ─── Helpers ───


def _make_orderbook(yes: list[list[int]] | None = None, no: list[list[int]] | None = None):
    """Create a mock KalshiOrderbook."""
    ob = MagicMock()
    ob.yes = yes if yes is not None else []
    ob.no = no if no is not None else []
    return ob


def _make_market(**overrides) -> MagicMock:
    """Create a mock KalshiMarket from get_event_markets."""
    market = MagicMock()
    market.ticker = overrides.get("ticker", "KXHIGHNY-26MAR14-B3")
    market.floor_strike = overrides.get("floor_strike", 55)
    market.cap_strike = overrides.get("cap_strike", 56.99)
    market.yes_ask = overrides.get("yes_ask", 0)
    market.last_price = overrides.get("last_price", 0)
    return market


# ─── best_yes_price_from_orderbook ───


class TestBestYesPriceFromOrderbook:
    """Unit tests for the orderbook price extraction helper."""

    def test_yes_side_picks_lowest_ask(self):
        """Should return the lowest YES ask price."""
        ob = _make_orderbook(yes=[[30, 5], [25, 10], [35, 3]])
        assert best_yes_price_from_orderbook(ob) == 25

    def test_yes_side_single_level(self):
        """Should work with a single level on the YES side."""
        ob = _make_orderbook(yes=[[42, 1]])
        assert best_yes_price_from_orderbook(ob) == 42

    def test_no_side_fallback(self):
        """When YES is empty, derive from best NO bid: 100 - max(no_bid)."""
        ob = _make_orderbook(no=[[70, 5], [75, 10], [65, 3]])
        # Best NO bid = 75, so YES price = 100 - 75 = 25
        assert best_yes_price_from_orderbook(ob) == 25

    def test_empty_orderbook_returns_none(self):
        """When both sides are empty, return None."""
        ob = _make_orderbook()
        assert best_yes_price_from_orderbook(ob) is None

    def test_yes_side_preferred_over_no(self):
        """If both sides have data, YES side is used (not NO)."""
        ob = _make_orderbook(yes=[[30, 5]], no=[[80, 10]])
        # YES side: lowest ask = 30
        # NO side would give: 100 - 80 = 20
        # YES side should be preferred
        assert best_yes_price_from_orderbook(ob) == 30


# ─── _fetch_market_prices with orderbook fallback ───


class TestFetchMarketPricesOrderbookFallback:
    """Tests for the orderbook fallback in _fetch_market_prices."""

    async def test_uses_yes_ask_when_available(self):
        """Fast path: when yes_ask > 0, use it directly without orderbook."""
        from backend.trading.scheduler import _fetch_market_prices

        market = _make_market(yes_ask=22, last_price=20)
        kalshi_client = AsyncMock()
        kalshi_client.get_event_markets.return_value = [market]

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with (
            patch(
                "backend.kalshi.cache.get_city_prices",
                AsyncMock(side_effect=Exception("no cache")),
            ),
            patch(
                "backend.kalshi.cache.get_redis_client",
                AsyncMock(return_value=mock_redis),
            ),
        ):
            prices = await _fetch_market_prices(kalshi_client, "NYC", date(2026, 3, 14))

        assert len(prices) == 1
        assert list(prices.values())[0] == 22
        # Should NOT have called get_orderbook
        kalshi_client.get_orderbook.assert_not_called()

    async def test_falls_back_to_orderbook_when_yes_ask_zero(self):
        """When yes_ask=0 and last_price=0, should call get_orderbook."""
        from backend.trading.scheduler import _fetch_market_prices

        market = _make_market(yes_ask=0, last_price=0, ticker="KXHIGHNY-26MAR14-B3")
        kalshi_client = AsyncMock()
        kalshi_client.get_event_markets.return_value = [market]
        kalshi_client.get_orderbook.return_value = _make_orderbook(yes=[[28, 10], [30, 5]])

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with (
            patch(
                "backend.kalshi.cache.get_city_prices",
                AsyncMock(side_effect=Exception("no cache")),
            ),
            patch(
                "backend.kalshi.cache.get_redis_client",
                AsyncMock(return_value=mock_redis),
            ),
        ):
            prices = await _fetch_market_prices(kalshi_client, "NYC", date(2026, 3, 14))

        assert list(prices.values())[0] == 28
        kalshi_client.get_orderbook.assert_called_once_with("KXHIGHNY-26MAR14-B3")

    async def test_orderbook_empty_skips_bracket(self):
        """When orderbook has no liquidity, bracket is skipped."""
        from backend.trading.scheduler import _fetch_market_prices

        market = _make_market(yes_ask=0, last_price=0)
        kalshi_client = AsyncMock()
        kalshi_client.get_event_markets.return_value = [market]
        kalshi_client.get_orderbook.return_value = _make_orderbook()  # empty

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with (
            patch(
                "backend.kalshi.cache.get_city_prices",
                AsyncMock(side_effect=Exception("no cache")),
            ),
            patch(
                "backend.kalshi.cache.get_redis_client",
                AsyncMock(return_value=mock_redis),
            ),
        ):
            prices = await _fetch_market_prices(kalshi_client, "NYC", date(2026, 3, 14))

        assert prices == {}

    async def test_orderbook_no_side_only(self):
        """When YES side empty but NO has data, derive price from NO bids."""
        from backend.trading.scheduler import _fetch_market_prices

        market = _make_market(yes_ask=0, last_price=0)
        kalshi_client = AsyncMock()
        kalshi_client.get_event_markets.return_value = [market]
        kalshi_client.get_orderbook.return_value = _make_orderbook(no=[[70, 5], [75, 10]])

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with (
            patch(
                "backend.kalshi.cache.get_city_prices",
                AsyncMock(side_effect=Exception("no cache")),
            ),
            patch(
                "backend.kalshi.cache.get_redis_client",
                AsyncMock(return_value=mock_redis),
            ),
        ):
            prices = await _fetch_market_prices(kalshi_client, "NYC", date(2026, 3, 14))

        # Best NO bid = 75, so YES price = 100 - 75 = 25
        assert list(prices.values())[0] == 25

    async def test_mixed_brackets_some_need_orderbook(self):
        """Some brackets have yes_ask, others need orderbook fallback."""
        from backend.trading.scheduler import _fetch_market_prices

        market_with_price = _make_market(
            yes_ask=15,
            last_price=15,
            ticker="KXHIGHNY-26MAR14-B1",
            floor_strike=None,
            cap_strike=52.99,
        )
        market_zero_price = _make_market(
            yes_ask=0,
            last_price=0,
            ticker="KXHIGHNY-26MAR14-B3",
            floor_strike=55,
            cap_strike=56.99,
        )
        kalshi_client = AsyncMock()
        kalshi_client.get_event_markets.return_value = [
            market_with_price,
            market_zero_price,
        ]
        kalshi_client.get_orderbook.return_value = _make_orderbook(yes=[[32, 5]])

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with (
            patch(
                "backend.kalshi.cache.get_city_prices",
                AsyncMock(side_effect=Exception("no cache")),
            ),
            patch(
                "backend.kalshi.cache.get_redis_client",
                AsyncMock(return_value=mock_redis),
            ),
        ):
            prices = await _fetch_market_prices(kalshi_client, "NYC", date(2026, 3, 14))

        # Should have two prices: one from yes_ask, one from orderbook
        assert len(prices) == 2
        values = list(prices.values())
        assert 15 in values
        assert 32 in values
        # Only the zero-price bracket should trigger orderbook call
        kalshi_client.get_orderbook.assert_called_once_with("KXHIGHNY-26MAR14-B3")

    async def test_orderbook_fallback_counter_incremented(self):
        """ORDERBOOK_FALLBACK_TOTAL counter should be incremented on fallback."""
        from backend.trading.scheduler import _fetch_market_prices

        market = _make_market(yes_ask=0, last_price=0, ticker="KXHIGHNY-26MAR14-B3")
        kalshi_client = AsyncMock()
        kalshi_client.get_event_markets.return_value = [market]
        kalshi_client.get_orderbook.return_value = _make_orderbook(yes=[[28, 10]])

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        mock_counter = MagicMock()

        with (
            patch(
                "backend.kalshi.cache.get_city_prices",
                AsyncMock(side_effect=Exception("no cache")),
            ),
            patch(
                "backend.kalshi.cache.get_redis_client",
                AsyncMock(return_value=mock_redis),
            ),
            patch(
                "backend.common.metrics.ORDERBOOK_FALLBACK_TOTAL",
                mock_counter,
            ),
        ):
            await _fetch_market_prices(kalshi_client, "NYC", date(2026, 3, 14))

        mock_counter.labels.assert_called_with(city="NYC")
        mock_counter.labels.return_value.inc.assert_called_once()

    async def test_orderbook_exception_handled_gracefully(self):
        """If get_orderbook raises, the bracket is skipped (not crash)."""
        from backend.trading.scheduler import _fetch_market_prices

        market = _make_market(yes_ask=0, last_price=0)
        kalshi_client = AsyncMock()
        kalshi_client.get_event_markets.return_value = [market]
        kalshi_client.get_orderbook.side_effect = Exception("API timeout")

        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with (
            patch(
                "backend.kalshi.cache.get_city_prices",
                AsyncMock(side_effect=Exception("no cache")),
            ),
            patch(
                "backend.kalshi.cache.get_redis_client",
                AsyncMock(return_value=mock_redis),
            ),
        ):
            prices = await _fetch_market_prices(kalshi_client, "NYC", date(2026, 3, 14))

        # Should not crash, just return empty prices for that bracket
        assert prices == {}

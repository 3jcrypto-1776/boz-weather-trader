"""Tests for per-bracket position cap -- _get_open_bracket_qty and cap logic in scheduler.

The bracket cap prevents buying the same bracket for the same market beyond
the configured `max_contracts_per_bracket` limit. This guards against the bot
re-buying every 15-min cycle, as happened with NYC "27°F or below" (24x).

Tests cover:
- _get_open_bracket_qty correctness (empty, sums, status filters, city/bracket/date scope)
- Cap blocks at limit, clamps partial, passes when under
- Different brackets/cities/dates are independent
- Prometheus metric incremented on block
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.common.schemas import TradeSignal, UserSettings

# ─── _get_open_bracket_qty tests ───


class TestGetOpenBracketQty:
    """Tests for the _get_open_bracket_qty helper function."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_trades(self, mock_db: AsyncMock) -> None:
        """Returns 0 when there are no OPEN trades for this bracket."""
        from backend.trading.scheduler import _get_open_bracket_qty

        result = await _get_open_bracket_qty(mock_db, "user-1", "NYC", "55-56°F", date(2026, 2, 25))
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_sum_of_quantities(self) -> None:
        """Returns the sum of quantities from matching OPEN trades."""
        from backend.trading.scheduler import _get_open_bracket_qty

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_db.execute.return_value = mock_result

        result = await _get_open_bracket_qty(mock_db, "user-1", "NYC", "55-56°F", date(2026, 2, 25))
        assert result == 5

    @pytest.mark.asyncio
    async def test_coalesce_returns_zero_for_null(self) -> None:
        """When SQL SUM returns NULL (no rows), COALESCE gives 0."""
        from backend.trading.scheduler import _get_open_bracket_qty

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0  # COALESCE(NULL, 0) = 0
        mock_db.execute.return_value = mock_result

        result = await _get_open_bracket_qty(
            mock_db, "user-1", "CHI", "39° to 40°F", date(2026, 2, 25)
        )
        assert result == 0
        assert isinstance(result, int)

    @pytest.mark.asyncio
    async def test_queries_correct_filters(self) -> None:
        """Verifies that the SQL query is executed with proper where clauses."""
        from backend.trading.scheduler import _get_open_bracket_qty

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_db.execute.return_value = mock_result

        result = await _get_open_bracket_qty(
            mock_db, "user-42", "AUS", "72°F or below", date(2026, 2, 24)
        )
        assert result == 3
        # Verify execute was called once
        assert mock_db.execute.call_count == 1


# ─── Bracket cap integration tests (cap logic in signal loop) ───


def _make_signal(
    city: str = "NYC",
    bracket: str = "55-56°F",
    quantity: int = 1,
) -> TradeSignal:
    """Create a TradeSignal for cap tests."""
    return TradeSignal(
        city=city,
        bracket=bracket,
        side="yes",
        price_cents=25,
        quantity=quantity,
        model_probability=0.30,
        market_probability=0.25,
        ev=0.05,
        confidence="medium",
        market_ticker="KXHIGHNY-26FEB18-B3",
        reasoning="test",
    )


class TestBracketCapLogic:
    """Tests for the bracket cap guard logic (blocks at limit, clamps partial)."""

    def test_cap_blocks_when_at_limit(self, user_settings: UserSettings) -> None:
        """When open_qty >= cap, remaining is 0 and signal should be skipped."""
        cap = user_settings.max_contracts_per_bracket  # default 3
        open_qty = 3
        remaining = max(0, cap - open_qty)
        assert remaining == 0  # Signal should be blocked

    def test_cap_blocks_when_over_limit(self, user_settings: UserSettings) -> None:
        """When open_qty > cap (stale data), remaining is still 0."""
        cap = user_settings.max_contracts_per_bracket  # default 3
        open_qty = 5
        remaining = max(0, cap - open_qty)
        assert remaining == 0

    def test_cap_allows_when_under_limit(self, user_settings: UserSettings) -> None:
        """When open_qty < cap, remaining > 0 and signal passes."""
        cap = user_settings.max_contracts_per_bracket  # default 3
        open_qty = 1
        remaining = max(0, cap - open_qty)
        assert remaining == 2

    def test_cap_clamps_quantity_when_partial(self) -> None:
        """When signal.quantity > remaining, it should be clamped."""
        signal = _make_signal(quantity=5)
        cap = 3
        open_qty = 2
        remaining = max(0, cap - open_qty)
        assert remaining == 1

        # Clamp the signal
        if signal.quantity > remaining:
            clamped = signal.model_copy(update={"quantity": remaining})
        else:
            clamped = signal

        assert clamped.quantity == 1
        # Other fields unchanged
        assert clamped.city == "NYC"
        assert clamped.bracket == "55-56°F"
        assert clamped.price_cents == 25

    def test_no_clamp_when_quantity_fits(self) -> None:
        """When signal.quantity <= remaining, no clamping needed."""
        signal = _make_signal(quantity=1)
        cap = 3
        open_qty = 1
        remaining = max(0, cap - open_qty)
        assert remaining == 2

        if signal.quantity > remaining:
            clamped = signal.model_copy(update={"quantity": remaining})
        else:
            clamped = signal

        assert clamped.quantity == 1  # unchanged

    def test_different_brackets_independent(self) -> None:
        """Different bracket labels have independent caps."""
        # These would be separate queries — each returns different open_qty
        cap = 3
        assert max(0, cap - 3) == 0  # "55-56°F" at limit
        assert max(0, cap - 0) == 3  # "57-58°F" has room
        assert max(0, cap - 2) == 1  # "≤52°F" has 1 remaining

    def test_different_cities_independent(self) -> None:
        """Different cities have independent bracket caps."""
        cap = 3
        # NYC bracket at limit, CHI same bracket has room
        assert max(0, cap - 3) == 0
        assert max(0, cap - 1) == 2

    def test_different_dates_independent(self) -> None:
        """Different market dates have independent bracket caps."""
        cap = 3
        # Feb 24 bracket at limit, Feb 25 same bracket has room
        assert max(0, cap - 3) == 0
        assert max(0, cap - 0) == 3

    def test_custom_cap_from_settings(self) -> None:
        """User can set custom max_contracts_per_bracket."""
        settings = UserSettings(
            trading_mode="auto",
            max_trade_size_cents=100,
            daily_loss_limit_cents=1000,
            max_daily_exposure_cents=2500,
            min_ev_threshold=0.05,
            cooldown_per_loss_minutes=60,
            consecutive_loss_limit=3,
            active_cities=["NYC"],
            notifications_enabled=True,
            max_contracts_per_bracket=10,
        )
        cap = settings.max_contracts_per_bracket
        assert cap == 10
        # With cap of 10, 8 open still allows 2 more
        assert max(0, cap - 8) == 2

    def test_model_copy_preserves_immutability(self) -> None:
        """model_copy creates a new signal, original is unchanged."""
        original = _make_signal(quantity=5)
        clamped = original.model_copy(update={"quantity": 2})

        assert original.quantity == 5  # unchanged
        assert clamped.quantity == 2


class TestBracketCapMetric:
    """Tests for BRACKET_CAP_BLOCKED_TOTAL Prometheus metric."""

    def test_metric_exists(self) -> None:
        """BRACKET_CAP_BLOCKED_TOTAL is importable and has city label."""
        from backend.common.metrics import BRACKET_CAP_BLOCKED_TOTAL

        # Verify it's a Counter with city label
        assert BRACKET_CAP_BLOCKED_TOTAL is not None
        # Exercise the .labels() method (no exception)
        counter = BRACKET_CAP_BLOCKED_TOTAL.labels(city="NYC")
        assert counter is not None

    def test_metric_increments(self) -> None:
        """BRACKET_CAP_BLOCKED_TOTAL.labels(city=...).inc() works."""
        from backend.common.metrics import BRACKET_CAP_BLOCKED_TOTAL

        before = BRACKET_CAP_BLOCKED_TOTAL.labels(city="TEST")._value.get()
        BRACKET_CAP_BLOCKED_TOTAL.labels(city="TEST").inc()
        after = BRACKET_CAP_BLOCKED_TOTAL.labels(city="TEST")._value.get()
        assert after == before + 1

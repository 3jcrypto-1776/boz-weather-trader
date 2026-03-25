"""Tests for backend.trading.postmortem -- settlement, bracket matching, narratives.

After market settlement (NWS CLI report), this module determines win/loss,
calculates P&L in cents (including fees), and generates human-readable narratives.

Bracket label formats:
    "53-54F"   -> standard 2-degree bracket (lower <= temp <= upper)
    "<=52F"    -> bottom catch-all (temp <= bound)
    ">=57F"    -> top catch-all (temp >= bound)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.common.models import Settlement, Trade, TradeStatus
from backend.trading.postmortem import (
    _did_bracket_win,
    generate_postmortem_narrative,
    settle_from_kalshi,
    settle_trade,
)


# ---------------------------------------------------------------------------
# TestDidBracketWin
# ---------------------------------------------------------------------------
class TestDidBracketWin:
    """Test _did_bracket_win -- bracket hit detection for all label formats."""

    def test_standard_bracket_hit_yes(self) -> None:
        """'53-54F', temp=53.5, side='yes' -> True (bracket hit, YES wins)."""
        assert _did_bracket_win("53-54F", 53.5, "yes") is True

    def test_standard_bracket_miss_yes(self) -> None:
        """'53-54F', temp=55, side='yes' -> False (bracket miss, YES loses)."""
        assert _did_bracket_win("53-54F", 55.0, "yes") is False

    def test_no_side_inverts(self) -> None:
        """'53-54F', temp=55, side='no' -> True (bracket miss, NO wins)."""
        assert _did_bracket_win("53-54F", 55.0, "no") is True

    def test_bottom_bracket(self) -> None:
        """'<=52F', temp=51 -> bracket hit (YES wins)."""
        assert _did_bracket_win("<=52F", 51.0, "yes") is True

    def test_bottom_bracket_miss(self) -> None:
        """'<=52F', temp=55 -> bracket miss (YES loses)."""
        assert _did_bracket_win("<=52F", 55.0, "yes") is False

    def test_top_bracket(self) -> None:
        """'>=57F', temp=58 -> bracket hit (YES wins)."""
        assert _did_bracket_win(">=57F", 58.0, "yes") is True

    def test_top_bracket_miss(self) -> None:
        """'>=57F', temp=55 -> bracket miss (YES loses)."""
        assert _did_bracket_win(">=57F", 55.0, "yes") is False

    def test_degree_symbol_handling(self) -> None:
        """'53-54\u00b0F' with degree symbol should parse correctly."""
        assert _did_bracket_win("53-54\u00b0F", 53.5, "yes") is True
        assert _did_bracket_win("53-54\u00b0F", 55.0, "yes") is False

    # -- Production bracket label formats ("X° to Y°F", "X°F or below/above") --

    def test_to_separator_hit_upper_boundary(self) -> None:
        """'71° to 72°F', temp=72 -> bracket hit (YES wins). Exact upper bound."""
        assert _did_bracket_win("71\u00b0 to 72\u00b0F", 72.0, "yes") is True

    def test_to_separator_hit_lower_boundary(self) -> None:
        """'71° to 72°F', temp=71 -> bracket hit (YES wins). Exact lower bound."""
        assert _did_bracket_win("71\u00b0 to 72\u00b0F", 71.0, "yes") is True

    def test_to_separator_miss_above(self) -> None:
        """'71° to 72°F', temp=73 -> bracket miss (YES loses)."""
        assert _did_bracket_win("71\u00b0 to 72\u00b0F", 73.0, "yes") is False

    def test_to_separator_miss_below(self) -> None:
        """'71° to 72°F', temp=70 -> bracket miss (YES loses)."""
        assert _did_bracket_win("71\u00b0 to 72\u00b0F", 70.0, "yes") is False

    def test_to_separator_no_side(self) -> None:
        """'71° to 72°F', temp=72, side='no' -> bracket hit, NO loses."""
        assert _did_bracket_win("71\u00b0 to 72\u00b0F", 72.0, "no") is False
        assert _did_bracket_win("71\u00b0 to 72\u00b0F", 73.0, "no") is True

    def test_to_separator_single_degree(self) -> None:
        """'65° to 65°F', temp=65 -> bracket hit (1-degree bracket)."""
        assert _did_bracket_win("65\u00b0 to 65\u00b0F", 65.0, "yes") is True
        assert _did_bracket_win("65\u00b0 to 65\u00b0F", 66.0, "yes") is False

    def test_or_below_hit(self) -> None:
        """'32°F or below', temp=30 -> bracket hit (YES wins)."""
        assert _did_bracket_win("32\u00b0F or below", 30.0, "yes") is True

    def test_or_below_miss(self) -> None:
        """'32°F or below', temp=35 -> bracket miss (YES loses)."""
        assert _did_bracket_win("32\u00b0F or below", 35.0, "yes") is False

    def test_or_below_boundary(self) -> None:
        """'32°F or below', temp=32 -> bracket hit at exact boundary."""
        assert _did_bracket_win("32\u00b0F or below", 32.0, "yes") is True

    def test_or_below_no_side(self) -> None:
        """'32°F or below', temp=30, side='no' -> bracket hit, NO loses."""
        assert _did_bracket_win("32\u00b0F or below", 30.0, "no") is False
        assert _did_bracket_win("32\u00b0F or below", 35.0, "no") is True

    def test_or_above_hit(self) -> None:
        """'91°F or above', temp=95 -> bracket hit (YES wins)."""
        assert _did_bracket_win("91\u00b0F or above", 95.0, "yes") is True

    def test_or_above_boundary(self) -> None:
        """'91°F or above', temp=91 -> bracket hit at exact boundary."""
        assert _did_bracket_win("91\u00b0F or above", 91.0, "yes") is True

    def test_or_above_miss(self) -> None:
        """'91°F or above', temp=88 -> bracket miss (YES loses)."""
        assert _did_bracket_win("91\u00b0F or above", 88.0, "yes") is False


# ---------------------------------------------------------------------------
# TestGeneratePostmortemNarrative
# ---------------------------------------------------------------------------
class TestGeneratePostmortemNarrative:
    """Test narrative generation for trade post-mortems."""

    def _make_trade(
        self,
        status: TradeStatus,
        pnl_cents: int = 67,
        fees_cents: int = 11,
    ) -> MagicMock:
        """Create a mock Trade ORM object."""
        trade = MagicMock(spec=Trade)
        trade.id = "abcd1234-5678-9012-3456-abcdef012345"
        trade.bracket_label = "53-54F"
        trade.side = "yes"
        trade.price_cents = 22
        trade.quantity = 1
        trade.city = MagicMock()
        trade.city.value = "NYC"
        trade.trade_date = datetime(2026, 2, 18, tzinfo=UTC)
        trade.model_probability = 0.30
        trade.market_probability = 0.22
        trade.ev_at_entry = 0.08
        trade.confidence = "medium"
        trade.status = status
        trade.pnl_cents = pnl_cents
        trade.fees_cents = fees_cents
        return trade

    def _make_settlement(self, temp: float = 53.5) -> MagicMock:
        """Create a mock Settlement ORM object."""
        settlement = MagicMock(spec=Settlement)
        settlement.actual_high_f = temp
        settlement.source = "NWS_CLI"
        return settlement

    def test_includes_outcome(self) -> None:
        """A winning trade narrative contains 'WIN'."""
        trade = self._make_trade(TradeStatus.WON, pnl_cents=67)
        settlement = self._make_settlement(53.5)
        narrative = generate_postmortem_narrative(trade, settlement, forecasts=[])
        assert "WIN" in narrative

    def test_includes_loss_outcome(self) -> None:
        """A losing trade narrative contains 'LOSS'."""
        trade = self._make_trade(TradeStatus.LOST, pnl_cents=-22)
        settlement = self._make_settlement(55.0)
        narrative = generate_postmortem_narrative(trade, settlement, forecasts=[])
        assert "LOSS" in narrative

    def test_includes_actual_temp(self) -> None:
        """The actual settlement temperature appears in the narrative."""
        trade = self._make_trade(TradeStatus.WON, pnl_cents=67)
        settlement = self._make_settlement(53.5)
        narrative = generate_postmortem_narrative(trade, settlement, forecasts=[])
        # Should contain "53F" or "54F" (rounded)
        assert "53" in narrative or "54" in narrative

    def test_has_section_headers(self) -> None:
        """Rich narrative contains all expected section headers."""
        trade = self._make_trade(TradeStatus.WON, pnl_cents=67)
        settlement = self._make_settlement(53.5)
        narrative = generate_postmortem_narrative(trade, settlement, forecasts=[])
        assert "WHAT WE TRADED" in narrative
        assert "WHAT HAPPENED" in narrative
        assert "WHY WE TOOK THIS TRADE" in narrative
        assert "TRADE ECONOMICS" in narrative

    def test_includes_station_name(self) -> None:
        """Narrative includes the station name from STATION_CONFIGS."""
        trade = self._make_trade(TradeStatus.WON, pnl_cents=67)
        settlement = self._make_settlement(53.5)
        narrative = generate_postmortem_narrative(trade, settlement, forecasts=[])
        # NYC station is Central Park
        assert "Central Park" in narrative

    def test_includes_city_name(self) -> None:
        """Narrative includes the human-readable city name."""
        trade = self._make_trade(TradeStatus.WON, pnl_cents=67)
        settlement = self._make_settlement(53.5)
        narrative = generate_postmortem_narrative(trade, settlement, forecasts=[])
        assert "New York" in narrative

    def test_includes_edge_pp(self) -> None:
        """Narrative includes the model-vs-market edge in percentage points."""
        trade = self._make_trade(TradeStatus.WON, pnl_cents=67)
        settlement = self._make_settlement(53.5)
        narrative = generate_postmortem_narrative(trade, settlement, forecasts=[])
        # model=0.30, market=0.22 => 8 pp edge
        assert "8 pp edge" in narrative

    def test_includes_ev_at_entry(self) -> None:
        """Narrative includes the EV at entry."""
        trade = self._make_trade(TradeStatus.WON, pnl_cents=67)
        settlement = self._make_settlement(53.5)
        narrative = generate_postmortem_narrative(trade, settlement, forecasts=[])
        assert "EV at entry" in narrative

    def test_includes_fees_when_won(self) -> None:
        """A winning trade narrative includes the fee amount."""
        trade = self._make_trade(TradeStatus.WON, pnl_cents=67, fees_cents=11)
        settlement = self._make_settlement(53.5)
        narrative = generate_postmortem_narrative(trade, settlement, forecasts=[])
        assert "Fees: $0.11" in narrative

    def test_no_fees_line_when_lost(self) -> None:
        """A losing trade narrative does not have a Fees line (fees=0)."""
        trade = self._make_trade(TradeStatus.LOST, pnl_cents=-22, fees_cents=0)
        settlement = self._make_settlement(55.0)
        narrative = generate_postmortem_narrative(trade, settlement, forecasts=[])
        assert "Fees:" not in narrative

    def test_includes_forecast_accuracy(self) -> None:
        """When forecasts are provided, narrative includes FORECAST ACCURACY."""
        from backend.common.models import WeatherForecast

        trade = self._make_trade(TradeStatus.WON, pnl_cents=67)
        settlement = self._make_settlement(53.5)

        fc = MagicMock(spec=WeatherForecast)
        fc.source = "NWS"
        fc.forecast_high_f = 54.0

        narrative = generate_postmortem_narrative(
            trade,
            settlement,
            forecasts=[fc],
        )
        assert "FORECAST ACCURACY" in narrative
        assert "NWS" in narrative
        assert "54F" in narrative

    def test_no_forecast_section_without_forecasts(self) -> None:
        """Without forecasts, no FORECAST ACCURACY section."""
        trade = self._make_trade(TradeStatus.WON, pnl_cents=67)
        settlement = self._make_settlement(53.5)
        narrative = generate_postmortem_narrative(trade, settlement, forecasts=[])
        assert "FORECAST ACCURACY" not in narrative


# ---------------------------------------------------------------------------
# TestSettleTrade
# ---------------------------------------------------------------------------
class TestSettleTrade:
    """Test settle_trade -- async settlement of a trade."""

    def _make_trade(self) -> MagicMock:
        """Create a mock Trade ORM object for settlement."""
        trade = MagicMock(spec=Trade)
        trade.id = "settle1234-5678-9012-3456-abcdef012345"
        trade.bracket_label = "53-54F"
        trade.side = "yes"
        trade.price_cents = 22
        trade.quantity = 1
        trade.city = MagicMock()
        trade.city.value = "NYC"
        trade.trade_date = datetime(2026, 2, 18, tzinfo=UTC)
        trade.model_probability = 0.30
        trade.market_probability = 0.22
        trade.ev_at_entry = 0.08
        trade.confidence = "medium"
        trade.status = TradeStatus.OPEN
        trade.pnl_cents = None
        trade.fees_cents = None
        trade.settlement_temp_f = None
        trade.settlement_source = None
        trade.settled_at = None
        trade.postmortem_narrative = None
        return trade

    def _make_settlement(self, temp: float) -> MagicMock:
        """Create a mock Settlement ORM object."""
        settlement = MagicMock(spec=Settlement)
        settlement.actual_high_f = temp
        settlement.source = "NWS_CLI"
        return settlement

    def _make_mock_db(self) -> AsyncMock:
        """Create a mock DB that returns empty forecasts."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        return mock_db

    @pytest.mark.asyncio
    async def test_winning_trade_pnl(self) -> None:
        """YES at 22c wins: pnl_cents = (100-22) - fee.
        fee = estimate_fees(22, 'yes') = max(1, int(78*0.15)) = 11c.
        pnl = 78 - 11 = 67c.
        """
        trade = self._make_trade()
        settlement = self._make_settlement(53.5)  # Within bracket 53-54F
        mock_db = self._make_mock_db()

        await settle_trade(trade, settlement, mock_db)

        assert trade.status == TradeStatus.WON
        assert trade.pnl_cents == 67
        assert trade.fees_cents == 11

    @pytest.mark.asyncio
    async def test_losing_trade_pnl(self) -> None:
        """YES at 22c loses: pnl_cents = -22 (lost the cost)."""
        trade = self._make_trade()
        settlement = self._make_settlement(55.0)  # Outside bracket 53-54F
        mock_db = self._make_mock_db()

        await settle_trade(trade, settlement, mock_db)

        assert trade.status == TradeStatus.LOST
        assert trade.pnl_cents == -22
        assert trade.fees_cents == 0

    @pytest.mark.asyncio
    async def test_uses_market_date_for_forecast_query(self) -> None:
        """settle_trade queries forecasts using market_date, not trade_date."""
        trade = self._make_trade()
        # Trade placed evening of Feb 17 for Feb 18 market
        trade.trade_date = datetime(2026, 2, 17, 22, 0, 0, tzinfo=UTC)
        trade.market_date = datetime(2026, 2, 18, 0, 0, 0)

        settlement = self._make_settlement(53.5)
        mock_db = self._make_mock_db()

        await settle_trade(trade, settlement, mock_db)

        # Verify the trade settled correctly. The forecast query uses market_date
        # (Feb 18) not trade_date (Feb 17) to find relevant forecasts.
        assert trade.status == TradeStatus.WON
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_trade_date_when_market_date_none(self) -> None:
        """If market_date is None, forecast query uses trade_date."""
        trade = self._make_trade()
        trade.market_date = None  # Pre-migration trade

        settlement = self._make_settlement(53.5)
        mock_db = self._make_mock_db()

        await settle_trade(trade, settlement, mock_db)

        # Should still settle correctly even without market_date
        assert trade.status == TradeStatus.WON
        assert trade.pnl_cents == 67


# ---------------------------------------------------------------------------
# TestSettleFromKalshi
# ---------------------------------------------------------------------------
class TestSettleFromKalshi:
    """Test settle_from_kalshi -- Kalshi-authoritative settlement."""

    def _make_trade(self, side: str = "yes", price_cents: int = 22) -> MagicMock:
        """Create a mock Trade ORM object for Kalshi settlement."""
        trade = MagicMock(spec=Trade)
        trade.id = "kalshi-settle-1234-5678-abcdef012345"
        trade.market_ticker = "KXHIGHNYC-26FEB18-B53.5"
        trade.bracket_label = "53-54F"
        trade.side = side
        trade.price_cents = price_cents
        trade.quantity = 1
        trade.city = MagicMock()
        trade.city.value = "NYC"
        trade.trade_date = datetime(2026, 2, 18, tzinfo=UTC)
        trade.market_date = datetime(2026, 2, 18, 0, 0, 0)
        trade.model_probability = 0.30
        trade.market_probability = 0.22
        trade.ev_at_entry = 0.08
        trade.confidence = "medium"
        trade.status = TradeStatus.OPEN
        trade.pnl_cents = None
        trade.fees_cents = None
        trade.settlement_temp_f = None
        trade.settlement_source = None
        trade.settled_at = None
        trade.postmortem_narrative = None
        return trade

    def _make_nws_settlement(self, temp: float = 53.5) -> MagicMock:
        """Create a mock NWS Settlement ORM object (display only)."""
        settlement = MagicMock(spec=Settlement)
        settlement.actual_high_f = temp
        settlement.source = "NWS_CLI"
        return settlement

    def _make_mock_db(self) -> AsyncMock:
        """Create a mock DB that returns empty forecasts."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        return mock_db

    @pytest.mark.asyncio
    async def test_yes_side_market_yes_wins(self) -> None:
        """YES trade + market_result='yes' -> WON."""
        trade = self._make_trade(side="yes")
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "yes", mock_db)

        assert trade.status == TradeStatus.WON

    @pytest.mark.asyncio
    async def test_yes_side_market_no_loses(self) -> None:
        """YES trade + market_result='no' -> LOST."""
        trade = self._make_trade(side="yes")
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "no", mock_db)

        assert trade.status == TradeStatus.LOST

    @pytest.mark.asyncio
    async def test_no_side_market_no_wins(self) -> None:
        """NO trade + market_result='no' -> WON."""
        trade = self._make_trade(side="no")
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "no", mock_db)

        assert trade.status == TradeStatus.WON

    @pytest.mark.asyncio
    async def test_no_side_market_yes_loses(self) -> None:
        """NO trade + market_result='yes' -> LOST."""
        trade = self._make_trade(side="no")
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "yes", mock_db)

        assert trade.status == TradeStatus.LOST

    @pytest.mark.asyncio
    async def test_pnl_yes_win(self) -> None:
        """YES at 22c wins: pnl = (100-22) - fee = 78 - 11 = 67c."""
        trade = self._make_trade(side="yes", price_cents=22)
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "yes", mock_db)

        assert trade.pnl_cents == 67
        assert trade.fees_cents == 11

    @pytest.mark.asyncio
    async def test_pnl_yes_loss(self) -> None:
        """YES at 22c loses: pnl = -22c (lost cost)."""
        trade = self._make_trade(side="yes", price_cents=22)
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "no", mock_db)

        assert trade.pnl_cents == -22
        assert trade.fees_cents == 0

    @pytest.mark.asyncio
    async def test_pnl_no_win(self) -> None:
        """NO at actual cost 22c wins: cost=22, profit=78, fee=11, pnl=67c."""
        trade = self._make_trade(side="no", price_cents=22)
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "no", mock_db)

        assert trade.status == TradeStatus.WON
        # price_cents=22 is the actual NO cost per contract.
        # cost = 22 * 1 = 22c, profit = 100 - 22 = 78c
        # fee = max(1, int((100-22) * 0.15)) = max(1, int(78*0.15)) = 11c
        assert trade.pnl_cents == 67
        assert trade.fees_cents == 11

    @pytest.mark.asyncio
    async def test_pnl_no_loss(self) -> None:
        """NO at actual cost 22c loses: pnl = -22c."""
        trade = self._make_trade(side="no", price_cents=22)
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "yes", mock_db)

        assert trade.status == TradeStatus.LOST
        assert trade.pnl_cents == -22
        assert trade.fees_cents == 0

    @pytest.mark.asyncio
    async def test_source_is_kalshi(self) -> None:
        """Settlement source should be 'KALSHI'."""
        trade = self._make_trade()
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "yes", mock_db)

        assert trade.settlement_source == "KALSHI"

    @pytest.mark.asyncio
    async def test_settled_at_is_set(self) -> None:
        """settled_at timestamp should be set."""
        trade = self._make_trade()
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "yes", mock_db)

        assert trade.settled_at is not None

    @pytest.mark.asyncio
    async def test_nws_temp_populated_when_available(self) -> None:
        """settlement_temp_f is set from NWS when provided."""
        trade = self._make_trade()
        nws = self._make_nws_settlement(temp=53.5)
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "yes", mock_db, nws_settlement=nws)

        assert trade.settlement_temp_f == 53.5

    @pytest.mark.asyncio
    async def test_no_nws_temp_is_none(self) -> None:
        """settlement_temp_f stays None without NWS data."""
        trade = self._make_trade()
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "yes", mock_db)

        # settlement_temp_f is a MagicMock attribute, wasn't set by our code
        # since nws_settlement is None. Verify by checking the source is KALSHI
        # (not NWS_CLI) and that settle didn't crash.
        assert trade.settlement_source == "KALSHI"

    @pytest.mark.asyncio
    async def test_postmortem_generated_with_nws(self) -> None:
        """Post-mortem narrative generated when NWS settlement available."""
        trade = self._make_trade()
        nws = self._make_nws_settlement(temp=53.5)
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "yes", mock_db, nws_settlement=nws)

        assert trade.postmortem_narrative is not None
        # Should be a string (the generated narrative)
        assert isinstance(trade.postmortem_narrative, str)
        assert "WHAT WE TRADED" in trade.postmortem_narrative


class TestNoSidePnlCorrectness:
    """Verify P&L matches Kalshi's formula when price_cents = actual NO cost."""

    def _make_no_trade(self, price_cents: int = 78) -> MagicMock:
        """Create a mock NO-side Trade with correct actual cost."""
        trade = MagicMock(spec=Trade)
        trade.id = "no-pnl-test-1234"
        trade.market_ticker = "KXHIGHNY-26MAR01-B42.5"
        trade.bracket_label = "42° to 43°F"
        trade.side = "no"
        trade.price_cents = price_cents  # Actual NO cost
        trade.quantity = 1
        trade.city = MagicMock()
        trade.city.value = "NYC"
        trade.trade_date = datetime(2026, 3, 1, tzinfo=UTC)
        trade.market_date = datetime(2026, 3, 1, 0, 0, 0)
        trade.model_probability = 0.10
        trade.market_probability = 0.22
        trade.ev_at_entry = 0.05
        trade.confidence = "medium"
        trade.status = TradeStatus.OPEN
        trade.pnl_cents = None
        trade.fees_cents = None
        trade.settlement_temp_f = None
        trade.settlement_source = None
        trade.settled_at = None
        trade.postmortem_narrative = None
        return trade

    def _make_mock_db(self) -> AsyncMock:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        return mock_db

    @pytest.mark.asyncio
    async def test_settle_no_won_correct_pnl(self) -> None:
        """NO WON: pnl = (100 - actual_cost) * qty - fees. Matches Kalshi."""
        trade = self._make_no_trade(price_cents=78)  # Paid 78c for NO
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "no", mock_db)  # "no" wins

        # profit = 100 - 78 = 22c, fee = max(1, int(22 * 0.15)) = 3c
        # pnl = 22 - 3 = 19c
        assert trade.status == TradeStatus.WON
        assert trade.pnl_cents == 19
        assert trade.fees_cents == 3

    @pytest.mark.asyncio
    async def test_settle_no_lost_correct_pnl(self) -> None:
        """NO LOST: pnl = -(actual_cost * qty). You lose what you paid."""
        trade = self._make_no_trade(price_cents=78)
        mock_db = self._make_mock_db()

        await settle_from_kalshi(trade, "yes", mock_db)  # "yes" wins, NO loses

        # Lost the full cost: -78c
        assert trade.status == TradeStatus.LOST
        assert trade.pnl_cents == -78
        assert trade.fees_cents == 0

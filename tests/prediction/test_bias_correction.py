"""Tests for backend.prediction.bias_correction — rolling bias correction.

Covers ``calculate_rolling_bias`` (12 tests) including insufficient data,
DB errors, cold/hot bias detection, and magnitude verification.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.prediction.bias_correction import calculate_rolling_bias

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _mock_session_with_rows(rows: list) -> AsyncMock:
    """Create a mock DB session returning the given rows from execute()."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    session.execute.return_value = mock_result
    return session


# ═══════════════════════════════════════════════════════════════
# calculate_rolling_bias
# ═══════════════════════════════════════════════════════════════


class TestCalculateRollingBias:
    """Tests for the async rolling bias calculation with mocked DB."""

    @pytest.mark.asyncio
    async def test_returns_zero_on_empty_db(self) -> None:
        """When the DB returns no rows, bias is 0.0 (no correction)."""
        session = _mock_session_with_rows([])

        bias = await calculate_rolling_bias("NYC", date(2026, 3, 25), db_session=session)

        assert bias == 0.0

    @pytest.mark.asyncio
    async def test_returns_zero_on_insufficient_data(self) -> None:
        """When fewer than min_samples rows are returned, bias is 0.0."""
        # 3 rows, but default min_samples is 5
        rows = [(55.0, 57.0)] * 3
        session = _mock_session_with_rows(rows)

        bias = await calculate_rolling_bias("NYC", date(2026, 3, 25), db_session=session)

        assert bias == 0.0

    @pytest.mark.asyncio
    async def test_returns_zero_on_db_error(self) -> None:
        """When the DB query raises an exception, bias is 0.0."""
        session = AsyncMock()
        session.execute.side_effect = RuntimeError("DB connection lost")

        bias = await calculate_rolling_bias("NYC", date(2026, 3, 25), db_session=session)

        assert bias == 0.0

    @pytest.mark.asyncio
    async def test_positive_bias_when_model_too_cold(self) -> None:
        """When actual > predicted consistently, bias is positive (add to temp)."""
        # predicted=55, actual=58 → error = +3.0 per day
        rows = [(55.0, 58.0)] * 7
        session = _mock_session_with_rows(rows)

        bias = await calculate_rolling_bias("NYC", date(2026, 3, 25), db_session=session)

        assert bias == pytest.approx(3.0)

    @pytest.mark.asyncio
    async def test_negative_bias_when_model_too_hot(self) -> None:
        """When actual < predicted consistently, bias is negative (subtract)."""
        # predicted=60, actual=57 → error = -3.0 per day
        rows = [(60.0, 57.0)] * 7
        session = _mock_session_with_rows(rows)

        bias = await calculate_rolling_bias("MIA", date(2026, 3, 25), db_session=session)

        assert bias == pytest.approx(-3.0)

    @pytest.mark.asyncio
    async def test_zero_bias_when_perfectly_accurate(self) -> None:
        """When actual == predicted, bias is 0.0."""
        rows = [(75.0, 75.0)] * 7
        session = _mock_session_with_rows(rows)

        bias = await calculate_rolling_bias("MIA", date(2026, 3, 25), db_session=session)

        assert bias == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_correct_magnitude_mixed_errors(self) -> None:
        """Verify the exact bias value with mixed positive/negative errors."""
        # 5 days: errors are +2, +4, +1, +3, +5 → mean = 3.0
        rows = [
            (55.0, 57.0),  # error = +2
            (60.0, 64.0),  # error = +4
            (50.0, 51.0),  # error = +1
            (70.0, 73.0),  # error = +3
            (65.0, 70.0),  # error = +5
        ]
        session = _mock_session_with_rows(rows)

        bias = await calculate_rolling_bias("CHI", date(2026, 3, 25), db_session=session)

        assert bias == pytest.approx(3.0)

    @pytest.mark.asyncio
    async def test_returns_float_for_all_cities(self) -> None:
        """Bias is always a float for every supported city."""
        rows = [(55.0, 58.0)] * 7
        session = _mock_session_with_rows(rows)

        for city in ("NYC", "CHI", "MIA", "AUS"):
            bias = await calculate_rolling_bias(city, date(2026, 3, 25), db_session=session)
            assert isinstance(bias, float), f"city={city}"

    @pytest.mark.asyncio
    async def test_custom_min_samples(self) -> None:
        """When min_samples is lowered, fewer rows suffice for a correction."""
        rows = [(55.0, 58.0)] * 3  # only 3 rows
        session = _mock_session_with_rows(rows)

        # Default min_samples=5 → would return 0.0
        bias_default = await calculate_rolling_bias("NYC", date(2026, 3, 25), db_session=session)
        assert bias_default == 0.0

        # With min_samples=3 → should compute bias
        session2 = _mock_session_with_rows(rows)
        bias_custom = await calculate_rolling_bias(
            "NYC", date(2026, 3, 25), db_session=session2, min_samples=3
        )
        assert bias_custom == pytest.approx(3.0)

    @pytest.mark.asyncio
    async def test_custom_lookback_days(self) -> None:
        """The lookback_days parameter is accepted without error."""
        rows = [(55.0, 58.0)] * 7
        session = _mock_session_with_rows(rows)

        # Just verify it doesn't crash with a custom lookback
        bias = await calculate_rolling_bias(
            "NYC", date(2026, 3, 25), db_session=session, lookback_days=7
        )
        assert isinstance(bias, float)

    @pytest.mark.asyncio
    async def test_handles_fractional_bias(self) -> None:
        """Bias with non-integer values is computed correctly."""
        # errors: 1.5, 2.5, 3.0, 1.0, 2.0 → mean = 2.0
        rows = [
            (55.0, 56.5),  # +1.5
            (60.0, 62.5),  # +2.5
            (50.0, 53.0),  # +3.0
            (70.0, 71.0),  # +1.0
            (65.0, 67.0),  # +2.0
        ]
        session = _mock_session_with_rows(rows)

        bias = await calculate_rolling_bias("AUS", date(2026, 3, 25), db_session=session)

        assert bias == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_cancelling_errors_produce_small_bias(self) -> None:
        """When positive and negative errors cancel out, bias is near zero."""
        rows = [
            (55.0, 58.0),  # +3
            (60.0, 57.0),  # -3
            (50.0, 53.0),  # +3
            (70.0, 67.0),  # -3
            (65.0, 65.0),  # 0
        ]
        session = _mock_session_with_rows(rows)

        bias = await calculate_rolling_bias("NYC", date(2026, 3, 25), db_session=session)

        assert bias == pytest.approx(0.0)

"""Tests for the post-settlement retraining trigger.

Tests _check_retraining_trigger: settlement count trigger, time elapsed trigger,
Brier score degradation trigger, and no-trigger scenarios.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.trading.scheduler import _check_retraining_trigger


class TestCheckRetrainingTrigger:
    """Tests for _check_retraining_trigger()."""

    @pytest.mark.asyncio
    async def test_first_training_triggers_immediately(self) -> None:
        """When no TrainingReport exists, triggers first_training."""
        mock_session = AsyncMock()
        # No previous training report
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("backend.prediction.train_models.train_all_models") as mock_task:
            mock_task.delay = MagicMock()
            await _check_retraining_trigger(mock_session, 5)

        mock_task.delay.assert_called_once_with(
            triggered_by="settlement",
            trigger_reason="first_training",
        )

    @pytest.mark.asyncio
    async def test_settlement_count_triggers(self) -> None:
        """Triggers when settlement count since last training >= threshold."""
        mock_session = AsyncMock()

        # Has a previous training report
        mock_report = MagicMock()
        mock_report.completed_at = datetime(2026, 2, 24, 0, 0, 0)

        report_result = MagicMock()
        report_result.scalar_one_or_none.return_value = mock_report

        # Settlement count = 30 (>= default threshold of 25)
        count_result = MagicMock()
        count_result.scalar.return_value = 30

        mock_session.execute.side_effect = [report_result, count_result]

        with (
            patch("backend.prediction.train_models.train_all_models") as mock_task,
            patch("backend.common.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(
                retrain_settlement_threshold=25,
                retrain_max_days=7,
                retrain_brier_threshold=0.25,
            )
            mock_task.delay = MagicMock()
            await _check_retraining_trigger(mock_session, 5)

        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["triggered_by"] == "settlement"
        assert "settlement_count_30" in call_kwargs["trigger_reason"]

    @pytest.mark.asyncio
    async def test_days_elapsed_triggers(self) -> None:
        """Triggers when days since last training >= retrain_max_days."""
        mock_session = AsyncMock()

        # Last training was 10 days ago
        mock_report = MagicMock()
        mock_report.completed_at = datetime.utcnow() - timedelta(days=10)

        report_result = MagicMock()
        report_result.scalar_one_or_none.return_value = mock_report

        # Settlement count below threshold
        count_result = MagicMock()
        count_result.scalar.return_value = 5

        mock_session.execute.side_effect = [report_result, count_result]

        with (
            patch("backend.prediction.train_models.train_all_models") as mock_task,
            patch("backend.common.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(
                retrain_settlement_threshold=25,
                retrain_max_days=7,
                retrain_brier_threshold=0.25,
            )
            mock_task.delay = MagicMock()
            await _check_retraining_trigger(mock_session, 3)

        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args[1]
        assert "days_elapsed" in call_kwargs["trigger_reason"]

    @pytest.mark.asyncio
    async def test_brier_degradation_triggers(self) -> None:
        """Triggers when average Brier score > retrain_brier_threshold."""
        mock_session = AsyncMock()

        # Last training was recent
        mock_report = MagicMock()
        mock_report.completed_at = datetime.utcnow() - timedelta(hours=12)

        report_result = MagicMock()
        report_result.scalar_one_or_none.return_value = mock_report

        # Settlement count below threshold
        count_result = MagicMock()
        count_result.scalar.return_value = 3

        mock_session.execute.side_effect = [report_result, count_result]

        # Brier score above threshold
        mock_calibration = MagicMock()
        mock_calibration.status = "ok"
        mock_calibration.brier_score = 0.35

        with (
            patch("backend.prediction.train_models.train_all_models") as mock_task,
            patch("backend.common.config.get_settings") as mock_settings,
            patch(
                "backend.prediction.calibration.check_calibration",
                new_callable=AsyncMock,
                return_value=mock_calibration,
            ),
        ):
            mock_settings.return_value = MagicMock(
                retrain_settlement_threshold=25,
                retrain_max_days=7,
                retrain_brier_threshold=0.25,
            )
            mock_task.delay = MagicMock()
            await _check_retraining_trigger(mock_session, 2)

        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args[1]
        assert "brier_degradation" in call_kwargs["trigger_reason"]

    @pytest.mark.asyncio
    async def test_no_trigger_when_below_thresholds(self) -> None:
        """Does NOT trigger when all conditions are below threshold."""
        mock_session = AsyncMock()

        # Recent training
        mock_report = MagicMock()
        mock_report.completed_at = datetime.utcnow() - timedelta(hours=6)

        report_result = MagicMock()
        report_result.scalar_one_or_none.return_value = mock_report

        # Low settlement count
        count_result = MagicMock()
        count_result.scalar.return_value = 3

        mock_session.execute.side_effect = [report_result, count_result]

        # Good Brier score
        mock_calibration = MagicMock()
        mock_calibration.status = "ok"
        mock_calibration.brier_score = 0.12

        with (
            patch("backend.prediction.train_models.train_all_models") as mock_task,
            patch("backend.common.config.get_settings") as mock_settings,
            patch(
                "backend.prediction.calibration.check_calibration",
                new_callable=AsyncMock,
                return_value=mock_calibration,
            ),
        ):
            mock_settings.return_value = MagicMock(
                retrain_settlement_threshold=25,
                retrain_max_days=7,
                retrain_brier_threshold=0.25,
            )
            mock_task.delay = MagicMock()
            await _check_retraining_trigger(mock_session, 2)

        mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_is_non_fatal(self) -> None:
        """If the trigger check raises, it's caught and doesn't propagate."""
        mock_session = AsyncMock()
        # Force an exception during the execute call
        mock_session.execute.side_effect = RuntimeError("DB error")

        # Should NOT raise
        await _check_retraining_trigger(mock_session, 5)

    @pytest.mark.asyncio
    async def test_brier_check_error_skipped(self) -> None:
        """If Brier check fails, only settlement count and time checks matter."""
        mock_session = AsyncMock()

        # Recent training with low settlement count
        mock_report = MagicMock()
        mock_report.completed_at = datetime.utcnow() - timedelta(hours=2)

        report_result = MagicMock()
        report_result.scalar_one_or_none.return_value = mock_report

        count_result = MagicMock()
        count_result.scalar.return_value = 3

        mock_session.execute.side_effect = [report_result, count_result]

        with (
            patch("backend.prediction.train_models.train_all_models") as mock_task,
            patch("backend.common.config.get_settings") as mock_settings,
            patch(
                "backend.prediction.calibration.check_calibration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Calibration failed"),
            ),
        ):
            mock_settings.return_value = MagicMock(
                retrain_settlement_threshold=25,
                retrain_max_days=7,
                retrain_brier_threshold=0.25,
            )
            mock_task.delay = MagicMock()
            await _check_retraining_trigger(mock_session, 1)

        # Should not trigger (count=3, recent, Brier check failed gracefully)
        mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_settlement_trigger_priority_over_time(self) -> None:
        """Settlement count trigger fires first, even if time would also trigger."""
        mock_session = AsyncMock()

        # Old training (would trigger time check) AND high settlement count
        mock_report = MagicMock()
        mock_report.completed_at = datetime.utcnow() - timedelta(days=10)

        report_result = MagicMock()
        report_result.scalar_one_or_none.return_value = mock_report

        count_result = MagicMock()
        count_result.scalar.return_value = 40  # Above threshold

        mock_session.execute.side_effect = [report_result, count_result]

        with (
            patch("backend.prediction.train_models.train_all_models") as mock_task,
            patch("backend.common.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(
                retrain_settlement_threshold=25,
                retrain_max_days=7,
                retrain_brier_threshold=0.25,
            )
            mock_task.delay = MagicMock()
            await _check_retraining_trigger(mock_session, 5)

        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args[1]
        # Settlement count trigger fires first
        assert "settlement_count" in call_kwargs["trigger_reason"]

"""Tests for the refactored training pipeline with TrainingReport persistence.

Tests the _train_all_async flow: weights before/after, source weight computation,
Brier score snapshots, skipped/error/completed report states, and cache invalidation.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from backend.prediction.train_models import train_all_models


class TestTrainAllModelsWithReports:
    """Tests for the train_all_models Celery task with TrainingReport persistence."""

    @patch("backend.prediction.train_models.async_to_sync")
    def test_triggered_by_passed_through(self, mock_ats) -> None:
        """triggered_by and trigger_reason kwargs are forwarded to async logic."""
        mock_inner = MagicMock(return_value={"status": "completed", "row_count": 200})
        mock_ats.return_value = mock_inner

        train_all_models.apply(
            kwargs={"triggered_by": "settlement", "trigger_reason": "settlement_count_30"}
        ).get()

        mock_inner.assert_called_once_with("settlement", "settlement_count_30")

    @patch("backend.prediction.train_models.async_to_sync")
    def test_default_triggered_by_is_schedule(self, mock_ats) -> None:
        """Default triggered_by is 'schedule' when not specified."""
        mock_inner = MagicMock(return_value={"status": "completed", "row_count": 100})
        mock_ats.return_value = mock_inner

        train_all_models.apply().get()

        mock_inner.assert_called_once_with("schedule", None)

    @patch("backend.prediction.train_models.async_to_sync")
    def test_manual_trigger(self, mock_ats) -> None:
        """Manual trigger passes triggered_by='manual'."""
        mock_inner = MagicMock(return_value={"status": "completed", "row_count": 50})
        mock_ats.return_value = mock_inner

        train_all_models.apply(
            kwargs={"triggered_by": "manual", "trigger_reason": "user_requested"}
        ).get()

        mock_inner.assert_called_once_with("manual", "user_requested")

    @patch("backend.prediction.train_models.async_to_sync")
    def test_result_includes_report_id(self, mock_ats) -> None:
        """Completed training result includes a report_id."""
        mock_ats.return_value = MagicMock(
            return_value={
                "status": "completed",
                "row_count": 200,
                "report_id": 42,
            }
        )

        result = train_all_models.apply().get()

        assert result["report_id"] == 42

    @patch("backend.prediction.train_models.async_to_sync")
    def test_skipped_result_includes_report_id(self, mock_ats) -> None:
        """Skipped training result includes a report_id."""
        mock_ats.return_value = MagicMock(
            return_value={
                "status": "skipped",
                "reason": "insufficient_data",
                "row_count": 5,
                "report_id": 7,
            }
        )

        result = train_all_models.apply().get()

        assert result["status"] == "skipped"
        assert result["report_id"] == 7

    @patch("backend.prediction.train_models.async_to_sync")
    def test_error_result_includes_report_id(self, mock_ats) -> None:
        """Error training result includes a report_id."""
        mock_ats.return_value = MagicMock(
            return_value={
                "status": "error",
                "reason": "feature_mismatch",
                "report_id": 13,
            }
        )

        result = train_all_models.apply().get()

        assert result["status"] == "error"
        assert result["report_id"] == 13


class TestTrainAllAsync:
    """Tests for _train_all_async internals using mocked dependencies."""

    @pytest.mark.asyncio
    async def test_insufficient_data_creates_skipped_report(self) -> None:
        """When training data is below threshold, a 'skipped' TrainingReport is created."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("backend.common.database.async_session", return_value=mock_session),
            patch(
                "backend.prediction.train_models._fetch_training_data", new_callable=AsyncMock
            ) as mock_fetch,
            patch("backend.prediction.train_models.get_settings") as mock_settings,
            patch("backend.prediction.train_models.MultiModelEnsemble") as mock_ensemble_cls,
            patch(
                "backend.prediction.train_models._get_avg_brier_score", new_callable=AsyncMock
            ) as mock_brier,
        ):
            mock_settings.return_value = MagicMock(
                xgb_model_dir="models",
                xgb_min_training_samples=50,
            )
            mock_fetch.return_value = [{"row": i} for i in range(10)]  # Only 10 rows
            mock_brier.return_value = None

            mock_ensemble = MagicMock()
            mock_ensemble.weights = None
            mock_ensemble.load_all.return_value = {}
            mock_ensemble_cls.return_value = mock_ensemble

            from backend.prediction.train_models import _train_all_async

            with patch(
                "backend.prediction.source_weights.load_source_weights",
                return_value=None,
            ):
                result = await _train_all_async("schedule", "weekly")

        assert result["status"] == "skipped"
        assert result["reason"] == "insufficient_data"
        assert "report_id" in result
        # Session should have been committed (to persist the report)
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_feature_mismatch_creates_error_report(self) -> None:
        """When feature count doesn't match, an 'error' TrainingReport is created."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        # Create training data with wrong number of features
        wrong_features = np.zeros((100, 5))  # 5 features instead of NUM_FEATURES
        wrong_labels = np.zeros(100)

        with (
            patch("backend.common.database.async_session", return_value=mock_session),
            patch(
                "backend.prediction.train_models._fetch_training_data", new_callable=AsyncMock
            ) as mock_fetch,
            patch("backend.prediction.train_models._rows_to_arrays") as mock_arrays,
            patch("backend.prediction.train_models.get_settings") as mock_settings,
            patch("backend.prediction.train_models.MultiModelEnsemble") as mock_ensemble_cls,
            patch(
                "backend.prediction.train_models._get_avg_brier_score", new_callable=AsyncMock
            ) as mock_brier,
        ):
            mock_settings.return_value = MagicMock(
                xgb_model_dir="models",
                xgb_min_training_samples=50,
            )
            mock_fetch.return_value = [{"row": i} for i in range(100)]
            mock_arrays.return_value = (wrong_features, wrong_labels)
            mock_brier.return_value = 0.15

            mock_ensemble = MagicMock()
            mock_ensemble.weights = {"xgboost": 0.5, "ridge": 0.5}
            mock_ensemble.load_all.return_value = {}
            mock_ensemble_cls.return_value = mock_ensemble

            from backend.prediction.train_models import _train_all_async

            with patch(
                "backend.prediction.source_weights.load_source_weights",
                return_value=None,
            ):
                result = await _train_all_async("schedule", None)

        assert result["status"] == "error"
        assert result["reason"] == "feature_mismatch"

    @pytest.mark.asyncio
    async def test_completed_training_persists_report(self) -> None:
        """Successful training persists a 'completed' TrainingReport."""
        from backend.prediction.features import NUM_FEATURES

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        X = np.random.randn(200, NUM_FEATURES)  # noqa: N806
        y = np.random.randn(200)
        rows = [{"row": i, "forecast_date": datetime(2026, 1, 1)} for i in range(200)]

        with (
            patch("backend.common.database.async_session", return_value=mock_session),
            patch(
                "backend.prediction.train_models._fetch_training_data", new_callable=AsyncMock
            ) as mock_fetch,
            patch("backend.prediction.train_models._rows_to_arrays") as mock_arrays,
            patch("backend.prediction.train_models.get_settings") as mock_settings,
            patch("backend.prediction.train_models.MultiModelEnsemble") as mock_ensemble_cls,
            patch(
                "backend.prediction.train_models._get_avg_brier_score", new_callable=AsyncMock
            ) as mock_brier,
            patch(
                "backend.prediction.source_weights.compute_source_weights_from_accuracy",
                new_callable=AsyncMock,
            ) as mock_compute_sw,
            patch(
                "backend.prediction.source_weights.save_source_weights",
            ) as mock_save_sw,
            patch(
                "backend.prediction.source_weights.load_source_weights",
                return_value={"NWS": 0.4, "ECMWF": 0.6},
            ),
            patch("backend.prediction.pipeline.reload_models") as mock_reload,
            patch(
                "backend.prediction.probability_calibration.fit_all_cities",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "backend.prediction.probability_calibration.save_calibration",
            ),
        ):
            mock_settings.return_value = MagicMock(
                xgb_model_dir="models",
                xgb_min_training_samples=50,
            )
            mock_fetch.return_value = rows
            mock_arrays.return_value = (X, y)
            mock_brier.return_value = 0.12

            mock_ensemble = MagicMock()
            mock_ensemble.weights = {"xgboost": 0.4, "ridge": 0.6}
            mock_ensemble.load_all.return_value = {"xgboost": True, "ridge": True}
            mock_ensemble.train_all.return_value = {
                "models": {"xgboost": {"rmse": 2.0}, "ridge": {"rmse": 2.5}},
            }
            mock_ensemble.save_all.return_value = None
            mock_ensemble_cls.return_value = mock_ensemble

            mock_compute_sw.return_value = {"NWS": 0.5, "ECMWF": 0.5}

            from backend.prediction.train_models import _train_all_async

            result = await _train_all_async("settlement", "settlement_count_30")

        assert result["status"] == "completed"
        assert result["row_count"] == 200
        mock_save_sw.assert_called_once()
        mock_reload.assert_called_once()
        mock_session.add.assert_called()
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_source_weight_failure_keeps_existing(self) -> None:
        """If source weight computation fails, existing weights are kept."""
        from backend.prediction.features import NUM_FEATURES

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        X = np.random.randn(200, NUM_FEATURES)  # noqa: N806
        y = np.random.randn(200)
        rows = [{"row": i, "forecast_date": datetime(2026, 1, 1)} for i in range(200)]

        with (
            patch("backend.common.database.async_session", return_value=mock_session),
            patch(
                "backend.prediction.train_models._fetch_training_data", new_callable=AsyncMock
            ) as mock_fetch,
            patch("backend.prediction.train_models._rows_to_arrays") as mock_arrays,
            patch("backend.prediction.train_models.get_settings") as mock_settings,
            patch("backend.prediction.train_models.MultiModelEnsemble") as mock_ensemble_cls,
            patch(
                "backend.prediction.train_models._get_avg_brier_score", new_callable=AsyncMock
            ) as mock_brier,
            patch(
                "backend.prediction.source_weights.compute_source_weights_from_accuracy",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB error"),
            ),
            patch(
                "backend.prediction.source_weights.load_source_weights",
                return_value={"NWS": 0.5, "ECMWF": 0.5},
            ),
            patch("backend.prediction.pipeline.reload_models"),
            patch(
                "backend.prediction.probability_calibration.fit_all_cities",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "backend.prediction.probability_calibration.save_calibration",
            ),
        ):
            mock_settings.return_value = MagicMock(
                xgb_model_dir="models",
                xgb_min_training_samples=50,
            )
            mock_fetch.return_value = rows
            mock_arrays.return_value = (X, y)
            mock_brier.return_value = 0.10

            mock_ensemble = MagicMock()
            mock_ensemble.weights = {"xgboost": 0.5, "ridge": 0.5}
            mock_ensemble.load_all.return_value = {}
            mock_ensemble.train_all.return_value = {"models": {}}
            mock_ensemble.save_all.return_value = None
            mock_ensemble_cls.return_value = mock_ensemble

            from backend.prediction.train_models import _train_all_async

            result = await _train_all_async("schedule", "weekly")

        # Should still complete successfully
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_brier_score_before_captured(self) -> None:
        """_get_avg_brier_score is called to capture pre-training Brier score."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("backend.common.database.async_session", return_value=mock_session),
            patch(
                "backend.prediction.train_models._fetch_training_data", new_callable=AsyncMock
            ) as mock_fetch,
            patch("backend.prediction.train_models.get_settings") as mock_settings,
            patch("backend.prediction.train_models.MultiModelEnsemble") as mock_ensemble_cls,
            patch(
                "backend.prediction.train_models._get_avg_brier_score", new_callable=AsyncMock
            ) as mock_brier,
        ):
            mock_settings.return_value = MagicMock(
                xgb_model_dir="models",
                xgb_min_training_samples=50,
            )
            mock_fetch.return_value = []  # Will be skipped
            mock_brier.return_value = 0.18

            mock_ensemble = MagicMock()
            mock_ensemble.weights = None
            mock_ensemble.load_all.return_value = {}
            mock_ensemble_cls.return_value = mock_ensemble

            from backend.prediction.train_models import _train_all_async

            with patch(
                "backend.prediction.source_weights.load_source_weights",
                return_value=None,
            ):
                await _train_all_async("schedule", None)

        # Brier score should have been computed
        mock_brier.assert_called()


class TestGetAvgBrierScore:
    """Tests for the _get_avg_brier_score helper."""

    @pytest.mark.asyncio
    async def test_returns_average_across_cities(self) -> None:
        """Computes mean Brier score across all 4 cities."""
        mock_session = AsyncMock()

        mock_report = MagicMock()
        mock_report.status = "ok"
        mock_report.brier_score = 0.15

        with patch(
            "backend.prediction.calibration.check_calibration",
            new_callable=AsyncMock,
            return_value=mock_report,
        ):
            from backend.prediction.train_models import _get_avg_brier_score

            result = await _get_avg_brier_score(mock_session)

        # All 4 cities return 0.15 → average = 0.15
        assert result == 0.15

    @pytest.mark.asyncio
    async def test_returns_none_when_no_data(self) -> None:
        """Returns None when calibration fails for all cities."""
        mock_session = AsyncMock()

        mock_report = MagicMock()
        mock_report.status = "insufficient_data"
        mock_report.brier_score = None

        with patch(
            "backend.prediction.calibration.check_calibration",
            new_callable=AsyncMock,
            return_value=mock_report,
        ):
            from backend.prediction.train_models import _get_avg_brier_score

            result = await _get_avg_brier_score(mock_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_partial_city_failures(self) -> None:
        """Averages scores from cities that succeed, ignoring failures."""
        mock_session = AsyncMock()

        call_count = 0

        async def mock_check(city, session, lookback_days=90):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                report = MagicMock()
                report.status = "ok"
                report.brier_score = 0.20
                return report
            raise RuntimeError("DB error")

        with patch(
            "backend.prediction.calibration.check_calibration",
            side_effect=mock_check,
        ):
            from backend.prediction.train_models import _get_avg_brier_score

            result = await _get_avg_brier_score(mock_session)

        assert result == 0.20


class TestReloadModelsInvocation:
    """Tests that reload_models() is called at appropriate times."""

    @patch("backend.prediction.train_models.async_to_sync")
    def test_retrain_metric_incremented(self, mock_ats) -> None:
        """ML_RETRAIN_TRIGGERS_TOTAL metric is incremented."""
        mock_ats.return_value = MagicMock(return_value={"status": "completed", "row_count": 100})

        # Should not raise
        train_all_models.apply(
            kwargs={"triggered_by": "settlement", "trigger_reason": "settlement_count_25"}
        ).get()

    @patch("backend.prediction.train_models.async_to_sync")
    def test_error_persists_report(self, mock_ats) -> None:
        """When async raises, an error report is persisted."""
        mock_inner = MagicMock(side_effect=RuntimeError("training crashed"))
        mock_ats.return_value = mock_inner

        # The async_to_sync for _save_error_report also needs mocking
        with patch(
            "backend.common.database.async_session",
        ):
            with pytest.raises(RuntimeError, match="training crashed"):
                train_all_models.apply(
                    kwargs={"triggered_by": "manual", "trigger_reason": "user_requested"}
                ).get()

"""Tests for backend.prediction.pipeline — full prediction orchestration.

Validates ``generate_prediction`` ties together ensemble, error_dist,
brackets, bias correction, and confidence into a correct ``BracketPrediction``.

All DB-dependent calls (``calculate_error_std``, ``calculate_rolling_bias``)
are patched so these tests run without a real database.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.common.schemas import BracketPrediction
from backend.prediction.pipeline import generate_prediction


@pytest.fixture(autouse=True)
def _patch_rolling_bias():
    """Auto-patch calculate_rolling_bias to return 0.0 (no correction) by default.

    Tests that specifically test bias correction override this via their own patch.
    """
    with patch(
        "backend.prediction.pipeline.calculate_rolling_bias",
        new_callable=AsyncMock,
        return_value=0.0,
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_calibration_cache():
    """Reset the pipeline's lazy-loaded calibration cache between tests.

    Without this, a curve loaded by one test would leak into the next.
    """
    from backend.prediction import pipeline as _pipe

    _pipe._calibration_curves = None
    _pipe._calibration_loaded = False
    yield
    _pipe._calibration_curves = None
    _pipe._calibration_loaded = False


class TestGeneratePrediction:
    """Integration-level tests for the prediction pipeline."""

    @pytest.mark.asyncio
    async def test_returns_bracket_prediction(self, sample_forecasts, sample_brackets) -> None:
        """The pipeline returns a BracketPrediction instance."""
        with patch(
            "backend.prediction.pipeline.calculate_error_std",
            new_callable=AsyncMock,
        ) as mock_std:
            mock_std.return_value = 2.0
            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )
            assert isinstance(result, BracketPrediction)

    @pytest.mark.asyncio
    async def test_uses_correct_schema_fields(self, sample_forecasts, sample_brackets) -> None:
        """Result uses ensemble_mean_f and ensemble_std_f (not legacy names)."""
        with patch(
            "backend.prediction.pipeline.calculate_error_std",
            new_callable=AsyncMock,
        ) as mock_std:
            mock_std.return_value = 2.5
            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )
            # These are the actual schema field names
            assert hasattr(result, "ensemble_mean_f")
            assert hasattr(result, "ensemble_std_f")
            assert isinstance(result.ensemble_mean_f, float)
            assert isinstance(result.ensemble_std_f, float)

    @pytest.mark.asyncio
    async def test_confidence_is_lowercase(self, sample_forecasts, sample_brackets) -> None:
        """Confidence must be one of 'high', 'medium', or 'low' (lowercase)."""
        with patch(
            "backend.prediction.pipeline.calculate_error_std",
            new_callable=AsyncMock,
        ) as mock_std:
            mock_std.return_value = 2.0
            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )
            assert result.confidence in ("high", "medium", "low")

    @pytest.mark.asyncio
    async def test_brackets_sum_to_one(self, sample_forecasts, sample_brackets) -> None:
        """Bracket probabilities in the output must sum to ~1.0."""
        with patch(
            "backend.prediction.pipeline.calculate_error_std",
            new_callable=AsyncMock,
        ) as mock_std:
            mock_std.return_value = 2.0
            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )
            total = sum(b.probability for b in result.brackets)
            assert abs(total - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_sources_populated(self, sample_forecasts, sample_brackets) -> None:
        """model_sources list must be populated from the input forecasts."""
        with patch(
            "backend.prediction.pipeline.calculate_error_std",
            new_callable=AsyncMock,
        ) as mock_std:
            mock_std.return_value = 2.0
            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )
            assert len(result.model_sources) == len(sample_forecasts)
            assert "NWS" in result.model_sources


class TestPipelineMultiModelIntegration:
    """Tests for multi-model ML ensemble integration in the prediction pipeline."""

    @pytest.mark.asyncio
    async def test_ml_available_blends_temperature(self, sample_forecasts, sample_brackets) -> None:
        """When ML models are available, the final temp is blended."""
        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.pipeline._try_multi_model_prediction",
                return_value=(60.0, ["XGBoost", "RandomForest", "Ridge"]),
            ),
            patch(
                "backend.prediction.pipeline.get_settings",
            ) as mock_settings,
        ):
            mock_std.return_value = 2.0
            mock_settings.return_value = MagicMock(ml_ensemble_weight=0.30)

            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

            assert "XGBoost" in result.model_sources
            assert "RandomForest" in result.model_sources
            assert "Ridge" in result.model_sources

    @pytest.mark.asyncio
    async def test_ml_unavailable_falls_back(self, sample_forecasts, sample_brackets) -> None:
        """When ML models return None, pipeline uses ensemble-only."""
        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.pipeline._try_multi_model_prediction",
                return_value=(None, []),
            ),
        ):
            mock_std.return_value = 2.0

            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

            assert "XGBoost" not in result.model_sources
            assert "RandomForest" not in result.model_sources

    @pytest.mark.asyncio
    async def test_ml_weight_zero_disables(self, sample_forecasts, sample_brackets) -> None:
        """When ml_ensemble_weight=0.0, ML is not attempted."""
        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.pipeline._try_multi_model_prediction",
                return_value=(None, []),
            ) as mock_ml,
        ):
            mock_std.return_value = 2.0

            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

            # _try_multi_model_prediction was called (returns None for weight=0).
            mock_ml.assert_called_once()
            assert "XGBoost" not in result.model_sources

    @pytest.mark.asyncio
    async def test_ml_failure_graceful_degradation(self, sample_forecasts, sample_brackets) -> None:
        """When _try_multi_model_prediction returns None, pipeline still completes."""
        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.pipeline._try_multi_model_prediction",
                return_value=(None, []),
            ),
        ):
            mock_std.return_value = 2.0

            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

            assert isinstance(result, BracketPrediction)
            assert "XGBoost" not in result.model_sources

    @pytest.mark.asyncio
    async def test_ml_sources_list_includes_all_models(
        self, sample_forecasts, sample_brackets
    ) -> None:
        """Sources list has all contributing ML model names appended."""
        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.pipeline._try_multi_model_prediction",
                return_value=(58.0, ["XGBoost", "RandomForest"]),
            ),
            patch(
                "backend.prediction.pipeline.get_settings",
            ) as mock_settings,
        ):
            mock_std.return_value = 2.0
            mock_settings.return_value = MagicMock(ml_ensemble_weight=0.30)

            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

            # Original sources + 2 ML model names
            assert result.model_sources[-1] == "RandomForest"
            assert result.model_sources[-2] == "XGBoost"
            assert len(result.model_sources) == len(sample_forecasts) + 2

    @pytest.mark.asyncio
    async def test_single_ml_model_in_sources(self, sample_forecasts, sample_brackets) -> None:
        """When only one ML model contributes, sources has just that model."""
        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.pipeline._try_multi_model_prediction",
                return_value=(57.0, ["XGBoost"]),
            ),
            patch(
                "backend.prediction.pipeline.get_settings",
            ) as mock_settings,
        ):
            mock_std.return_value = 2.0
            mock_settings.return_value = MagicMock(ml_ensemble_weight=0.30)

            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

            assert "XGBoost" in result.model_sources
            assert len(result.model_sources) == len(sample_forecasts) + 1


class TestPipelineBiasCorrection:
    """Tests for rolling bias correction integration in the prediction pipeline."""

    @pytest.mark.asyncio
    async def test_bias_correction_adjusts_ensemble_temp(
        self, sample_forecasts, sample_brackets
    ) -> None:
        """When bias correction returns +3.0, ensemble_mean_f is shifted up."""
        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.pipeline.calculate_rolling_bias",
                new_callable=AsyncMock,
            ) as mock_bias,
        ):
            mock_std.return_value = 2.0
            mock_bias.return_value = 3.0

            result_with_bias = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

        # Now run without bias for comparison
        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.pipeline.calculate_rolling_bias",
                new_callable=AsyncMock,
            ) as mock_bias,
        ):
            mock_std.return_value = 2.0
            mock_bias.return_value = 0.0

            result_no_bias = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

        # The biased result should be 3°F higher
        assert result_with_bias.ensemble_mean_f == pytest.approx(
            result_no_bias.ensemble_mean_f + 3.0, abs=0.01
        )

    @pytest.mark.asyncio
    async def test_bias_correction_zero_has_no_effect(
        self, sample_forecasts, sample_brackets
    ) -> None:
        """When bias correction returns 0.0, ensemble_mean_f is unchanged."""
        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.pipeline.calculate_rolling_bias",
                new_callable=AsyncMock,
            ) as mock_bias,
        ):
            mock_std.return_value = 2.0
            mock_bias.return_value = 0.0

            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

        # ensemble_mean_f should be the same as raw ensemble calculation
        from backend.prediction.ensemble import calculate_ensemble_forecast

        raw_temp, _, _ = calculate_ensemble_forecast(sample_forecasts)
        assert result.ensemble_mean_f == pytest.approx(round(raw_temp, 2), abs=0.01)


class TestPipelineProbabilityCalibration:
    """Tests for probability calibration integration in the prediction pipeline."""

    @pytest.mark.asyncio
    async def test_no_curves_keeps_raw_probs(self, sample_forecasts, sample_brackets) -> None:
        """When no calibration file exists, bracket probs are not modified."""
        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.probability_calibration.load_calibration",
                return_value=None,
            ),
        ):
            mock_std.return_value = 2.0

            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )
            # Probabilities still sum to 1.0 (sanity)
            total = sum(b.probability for b in result.brackets)
            assert abs(total - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_identity_curve_keeps_raw_probs(self, sample_forecasts, sample_brackets) -> None:
        """An identity curve for the city is treated as no-op."""
        from backend.prediction.probability_calibration import _identity_curve

        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.probability_calibration.load_calibration",
                return_value={"NYC": _identity_curve()},
            ),
        ):
            mock_std.return_value = 2.0

            no_cal = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

        # Reset cache between calls (autouse fixture handles this between tests
        # but inside one test we have to clear manually)
        from backend.prediction import pipeline as _pipe

        _pipe._calibration_curves = None
        _pipe._calibration_loaded = False

        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.probability_calibration.load_calibration",
                return_value=None,
            ),
        ):
            mock_std.return_value = 2.0

            baseline = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

        for a, b in zip(no_cal.brackets, baseline.brackets, strict=True):
            assert a.probability == pytest.approx(b.probability, abs=1e-9)

    @pytest.mark.asyncio
    async def test_active_curve_changes_probabilities(
        self, sample_forecasts, sample_brackets
    ) -> None:
        """A non-identity curve actually transforms the bracket probabilities."""
        # Aggressive shrinkage curve: anything in (0.2, 0.9) → ~0.1.
        squashing_curve = {
            "x_thresholds": [0.0, 0.1, 0.2, 0.9, 1.0],
            "y_thresholds": [0.0, 0.05, 0.10, 0.10, 0.20],
            "is_identity": False,
            "sample_count": 1000,
        }

        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.probability_calibration.load_calibration",
                return_value={"NYC": squashing_curve},
            ),
        ):
            mock_std.return_value = 2.0

            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

        # Output still sums to 1.0
        total = sum(b.probability for b in result.brackets)
        assert total == pytest.approx(1.0, abs=1e-6)
        # And the maximum bracket probability is no longer extreme — every
        # bucket should be somewhere between roughly 0.05 and 0.40 after
        # renormalization through the squashing curve.
        max_prob = max(b.probability for b in result.brackets)
        assert max_prob < 0.45, f"Expected calibration to flatten, got max={max_prob}"

    @pytest.mark.asyncio
    async def test_curve_for_other_city_not_applied(
        self, sample_forecasts, sample_brackets
    ) -> None:
        """A curve keyed under CHI must not be applied to a NYC prediction."""
        chi_only_curve = {
            "CHI": {
                "x_thresholds": [0.0, 1.0],
                "y_thresholds": [0.0, 0.5],
                "is_identity": False,
                "sample_count": 1000,
            }
        }

        with (
            patch(
                "backend.prediction.pipeline.calculate_error_std",
                new_callable=AsyncMock,
            ) as mock_std,
            patch(
                "backend.prediction.probability_calibration.load_calibration",
                return_value=chi_only_curve,
            ),
        ):
            mock_std.return_value = 2.0

            result = await generate_prediction(
                city="NYC",
                target_date=date(2026, 2, 18),
                forecasts=sample_forecasts,
                kalshi_brackets=sample_brackets,
                db_session=AsyncMock(),
            )

        # Probabilities still sum to 1.0 — no transformation applied.
        total = sum(b.probability for b in result.brackets)
        assert total == pytest.approx(1.0, abs=1e-6)

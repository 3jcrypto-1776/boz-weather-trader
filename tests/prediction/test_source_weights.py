"""Tests for source weight persistence and computation.

Tests the save/load round-trip, corrupt file handling, and the
inverse-RMSE weight computation from accuracy data.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.prediction.source_weights import (
    _MIN_SAMPLES_PER_SOURCE,
    compute_source_weights_from_accuracy,
    load_source_weights,
    save_source_weights,
)

# ─── load / save tests ───


class TestLoadSourceWeights:
    """Tests for load_source_weights()."""

    def test_load_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = load_source_weights(str(tmp_path))
        assert result is None

    def test_load_valid_file(self, tmp_path: Path) -> None:
        weights = {"NWS": 0.4, "Open-Meteo:GFS": 0.6}
        data = {"weights": weights, "computed_at": "2026-02-24T00:00:00"}
        (tmp_path / "source_weights.json").write_text(json.dumps(data))

        result = load_source_weights(str(tmp_path))
        assert result == weights

    def test_load_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "source_weights.json").write_text("not valid json {{{")
        result = load_source_weights(str(tmp_path))
        assert result is None

    def test_load_empty_weights_returns_none(self, tmp_path: Path) -> None:
        data = {"weights": {}}
        (tmp_path / "source_weights.json").write_text(json.dumps(data))
        result = load_source_weights(str(tmp_path))
        assert result is None

    def test_load_missing_weights_key_returns_none(self, tmp_path: Path) -> None:
        data = {"other": "stuff"}
        (tmp_path / "source_weights.json").write_text(json.dumps(data))
        result = load_source_weights(str(tmp_path))
        assert result is None


class TestSaveSourceWeights:
    """Tests for save_source_weights()."""

    def test_save_creates_file(self, tmp_path: Path) -> None:
        weights = {"NWS": 0.5, "Open-Meteo:ECMWF": 0.5}
        save_source_weights(weights, str(tmp_path))

        path = tmp_path / "source_weights.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["weights"] == weights
        assert "computed_at" in data

    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        weights = {
            "NWS": 0.35,
            "Open-Meteo:ECMWF": 0.30,
            "Open-Meteo:GFS": 0.20,
            "Open-Meteo:ICON": 0.15,
        }
        save_source_weights(weights, str(tmp_path))
        loaded = load_source_weights(str(tmp_path))
        assert loaded == weights

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "nested" / "models"
        weights = {"NWS": 1.0}
        save_source_weights(weights, str(new_dir))
        assert (new_dir / "source_weights.json").exists()


# ─── compute_source_weights_from_accuracy tests ───


class TestComputeSourceWeightsFromAccuracy:
    """Tests for compute_source_weights_from_accuracy()."""

    @pytest.mark.asyncio
    async def test_sufficient_data_returns_inverse_rmse_weights(self) -> None:
        """With good accuracy data, weights should be inverse-RMSE normalized."""
        mock_accuracy = MagicMock()
        mock_accuracy.source = "NWS"
        mock_accuracy.sample_count = 30
        mock_accuracy.rmse_f = 2.0

        mock_accuracy2 = MagicMock()
        mock_accuracy2.source = "Open-Meteo:ECMWF"
        mock_accuracy2.sample_count = 30
        mock_accuracy2.rmse_f = 3.0

        async def mock_get_source_accuracy(city, session, lookback_days=90):
            return [mock_accuracy, mock_accuracy2]

        session = AsyncMock()
        with patch(
            "backend.prediction.accuracy.get_source_accuracy",
            side_effect=mock_get_source_accuracy,
        ):
            weights = await compute_source_weights_from_accuracy(session)

        assert "NWS" in weights
        assert "Open-Meteo:ECMWF" in weights
        # NWS has lower RMSE (2.0) → should have higher weight
        assert weights["NWS"] > weights["Open-Meteo:ECMWF"]
        # Weights should sum to ~1.0
        assert abs(sum(weights.values()) - 1.0) < 0.01

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_defaults(self) -> None:
        """With no accuracy data, should return DEFAULT_MODEL_WEIGHTS."""
        from backend.prediction.ensemble import DEFAULT_MODEL_WEIGHTS

        async def mock_get_source_accuracy(city, session, lookback_days=90):
            return []

        session = AsyncMock()
        with patch(
            "backend.prediction.accuracy.get_source_accuracy",
            side_effect=mock_get_source_accuracy,
        ):
            weights = await compute_source_weights_from_accuracy(session)

        assert weights == DEFAULT_MODEL_WEIGHTS

    @pytest.mark.asyncio
    async def test_low_sample_sources_excluded(self) -> None:
        """Sources with fewer than _MIN_SAMPLES_PER_SOURCE should be excluded."""
        good_source = MagicMock()
        good_source.source = "NWS"
        good_source.sample_count = 30
        good_source.rmse_f = 2.0

        bad_source = MagicMock()
        bad_source.source = "Open-Meteo:GEM"
        bad_source.sample_count = _MIN_SAMPLES_PER_SOURCE - 1  # Too few samples
        bad_source.rmse_f = 1.0

        async def mock_get_source_accuracy(city, session, lookback_days=90):
            return [good_source, bad_source]

        session = AsyncMock()
        with patch(
            "backend.prediction.accuracy.get_source_accuracy",
            side_effect=mock_get_source_accuracy,
        ):
            weights = await compute_source_weights_from_accuracy(session)

        assert "NWS" in weights
        assert "Open-Meteo:GEM" not in weights

    @pytest.mark.asyncio
    async def test_zero_rmse_sources_excluded(self) -> None:
        """Sources with RMSE=0 are excluded from weight computation (filtered at collection)."""
        perfect_source = MagicMock()
        perfect_source.source = "PerfectModel"
        perfect_source.sample_count = 30
        perfect_source.rmse_f = 0.0  # Zero RMSE → excluded by src.rmse_f > 0 filter

        ok_source = MagicMock()
        ok_source.source = "OkModel"
        ok_source.sample_count = 30
        ok_source.rmse_f = 2.0

        async def mock_get_source_accuracy(city, session, lookback_days=90):
            return [perfect_source, ok_source]

        session = AsyncMock()
        with patch(
            "backend.prediction.accuracy.get_source_accuracy",
            side_effect=mock_get_source_accuracy,
        ):
            weights = await compute_source_weights_from_accuracy(session)

        # PerfectModel excluded because RMSE=0 is filtered out
        assert "PerfectModel" not in weights
        # OkModel gets 100% of the weight
        assert weights.get("OkModel", 0) == pytest.approx(1.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_accuracy_error_falls_back_to_defaults(self) -> None:
        """If get_source_accuracy raises for all cities, return defaults."""
        from backend.prediction.ensemble import DEFAULT_MODEL_WEIGHTS

        async def mock_get_source_accuracy(city, session, lookback_days=90):
            raise RuntimeError("DB error")

        session = AsyncMock()
        with patch(
            "backend.prediction.accuracy.get_source_accuracy",
            side_effect=mock_get_source_accuracy,
        ):
            weights = await compute_source_weights_from_accuracy(session)

        assert weights == DEFAULT_MODEL_WEIGHTS

    @pytest.mark.asyncio
    async def test_weights_sum_to_one(self) -> None:
        """Computed weights should always sum to approximately 1.0."""
        sources = []
        for name, rmse in [("NWS", 2.1), ("ECMWF", 1.8), ("GFS", 2.5), ("ICON", 3.0)]:
            s = MagicMock()
            s.source = name
            s.sample_count = 50
            s.rmse_f = rmse
            sources.append(s)

        async def mock_get_source_accuracy(city, session, lookback_days=90):
            return sources

        session = AsyncMock()
        with patch(
            "backend.prediction.accuracy.get_source_accuracy",
            side_effect=mock_get_source_accuracy,
        ):
            weights = await compute_source_weights_from_accuracy(session)

        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"Weights sum to {total}, expected ~1.0"

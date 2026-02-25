"""Tests for the training reports API endpoints.

Tests GET /api/training/reports and POST /api/training/trigger.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.models import TrainingReport

pytestmark = pytest.mark.asyncio


# ─── Helpers ───


def _make_report(
    triggered_by: str = "schedule",
    trigger_reason: str | None = "weekly",
    status: str = "completed",
    training_samples: int = 200,
    test_samples: int = 50,
    model_metrics: dict | None = None,
    duration_seconds: float = 12.5,
    completed_at: datetime | None = None,
    brier_score_before: float | None = None,
    brier_score_after: float | None = None,
) -> TrainingReport:
    """Create a TrainingReport ORM model with defaults."""
    return TrainingReport(
        triggered_by=triggered_by,
        trigger_reason=trigger_reason,
        status=status,
        training_samples=training_samples,
        test_samples=test_samples,
        model_metrics=model_metrics
        or {
            "xgboost": {"rmse": 2.1, "mae": 1.5, "accepted": True},
            "ridge": {"rmse": 2.8, "mae": 2.0, "accepted": True},
        },
        weights_before={"xgboost": 0.5, "ridge": 0.5},
        weights_after={"xgboost": 0.55, "ridge": 0.45},
        source_weights_before={"NWS": 0.4, "ECMWF": 0.6},
        source_weights_after={"NWS": 0.45, "ECMWF": 0.55},
        brier_score_before=brier_score_before or 0.18,
        brier_score_after=brier_score_after or 0.16,
        duration_seconds=duration_seconds,
        started_at=datetime.now(UTC).replace(tzinfo=None),
        completed_at=completed_at or datetime.now(UTC).replace(tzinfo=None),
    )


# ─── GET /api/training/reports ───


class TestGetTrainingReports:
    """Tests for GET /api/training/reports."""

    async def test_empty_reports(self, client: AsyncClient) -> None:
        """Returns empty list when no training reports exist."""
        resp = await client.get("/api/training/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reports"] == []
        assert data["total"] == 0

    async def test_returns_reports(self, client: AsyncClient, db: AsyncSession) -> None:
        """Returns training reports with all fields populated."""
        report = _make_report()
        db.add(report)
        await db.commit()

        resp = await client.get("/api/training/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["reports"]) == 1

        r = data["reports"][0]
        assert r["triggered_by"] == "schedule"
        assert r["status"] == "completed"
        assert r["training_samples"] == 200
        assert r["test_samples"] == 50
        assert r["weights_before"] is not None
        assert r["weights_after"] is not None
        assert r["source_weights_before"] is not None
        assert r["source_weights_after"] is not None
        assert r["brier_score_before"] == pytest.approx(0.18, abs=0.01)
        assert r["duration_seconds"] > 0

    async def test_pagination(self, client: AsyncClient, db: AsyncSession) -> None:
        """Respects limit and offset parameters."""
        now = datetime.now(UTC).replace(tzinfo=None)
        for i in range(5):
            report = _make_report(
                completed_at=now - timedelta(hours=i),
                duration_seconds=float(i),
            )
            db.add(report)
        await db.commit()

        resp = await client.get("/api/training/reports?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["reports"]) == 2
        assert data["total"] == 5

    async def test_newest_first_ordering(self, client: AsyncClient, db: AsyncSession) -> None:
        """Reports are returned in reverse chronological order."""
        now = datetime.now(UTC).replace(tzinfo=None)

        old_report = _make_report(
            trigger_reason="old",
            completed_at=now - timedelta(days=5),
        )
        new_report = _make_report(
            trigger_reason="new",
            completed_at=now,
        )
        db.add(old_report)
        db.add(new_report)
        await db.commit()

        resp = await client.get("/api/training/reports")
        assert resp.status_code == 200
        data = resp.json()
        # Newest first
        assert data["reports"][0]["trigger_reason"] == "new"
        assert data["reports"][1]["trigger_reason"] == "old"

    async def test_model_metrics_parsed(self, client: AsyncClient, db: AsyncSession) -> None:
        """Model metrics JSON is parsed into structured list."""
        report = _make_report(
            model_metrics={
                "xgboost": {"rmse": 2.0, "mae": 1.4, "accepted": True},
                "ridge": {"rmse": 3.0, "mae": 2.2, "accepted": False, "error": "RMSE too high"},
            }
        )
        db.add(report)
        await db.commit()

        resp = await client.get("/api/training/reports")
        data = resp.json()
        metrics = data["reports"][0]["model_metrics"]
        assert len(metrics) == 2

        xgb = next(m for m in metrics if m["model_name"] == "xgboost")
        assert xgb["rmse"] == 2.0
        assert xgb["accepted"] is True

        ridge = next(m for m in metrics if m["model_name"] == "ridge")
        assert ridge["accepted"] is False
        assert ridge["error"] == "RMSE too high"

    async def test_skipped_report(self, client: AsyncClient, db: AsyncSession) -> None:
        """Skipped report renders with empty metrics."""
        report = _make_report(
            status="skipped",
            training_samples=0,
            test_samples=0,
            model_metrics={"reason": "insufficient_data", "row_count": 10},
        )
        db.add(report)
        await db.commit()

        resp = await client.get("/api/training/reports")
        data = resp.json()
        r = data["reports"][0]
        assert r["status"] == "skipped"
        assert r["training_samples"] == 0

    async def test_offset_beyond_total(self, client: AsyncClient, db: AsyncSession) -> None:
        """Offset beyond total returns empty list but correct total."""
        report = _make_report()
        db.add(report)
        await db.commit()

        resp = await client.get("/api/training/reports?offset=100")
        data = resp.json()
        assert data["reports"] == []
        assert data["total"] == 1

    async def test_limit_validation(self, client: AsyncClient) -> None:
        """Limit must be between 1 and 50."""
        resp = await client.get("/api/training/reports?limit=0")
        assert resp.status_code == 422

        resp = await client.get("/api/training/reports?limit=100")
        assert resp.status_code == 422

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        """Returns 401 when not authenticated."""
        resp = await unauthed_client.get("/api/training/reports")
        assert resp.status_code == 401


# ─── POST /api/training/trigger ───


class TestTriggerRetraining:
    """Tests for POST /api/training/trigger."""

    async def test_trigger_dispatches_task(self, client: AsyncClient) -> None:
        """Dispatches the train_all_models Celery task."""
        with patch("backend.prediction.train_models.train_all_models") as mock_task:
            mock_task.delay = MagicMock()
            resp = await client.post("/api/training/trigger")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "dispatched"
        mock_task.delay.assert_called_once_with(
            triggered_by="manual",
            trigger_reason="user_requested",
        )

    async def test_trigger_requires_auth(self, unauthed_client: AsyncClient) -> None:
        """Returns 401 when not authenticated."""
        resp = await unauthed_client.post("/api/training/trigger")
        assert resp.status_code == 401

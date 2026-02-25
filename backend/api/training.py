"""Training report endpoints.

Provides training history data for the Performance page's Training Log section,
and allows manual triggering of model retraining.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.response_schemas import (
    ModelMetricsResponse,
    TrainingReportListResponse,
    TrainingReportResponse,
    UpdateTriggerResponse,
)
from backend.common.database import get_db
from backend.common.logging import get_logger
from backend.common.models import TrainingReport, User

logger = get_logger("MODEL")

router = APIRouter()


def _report_to_response(report: TrainingReport) -> TrainingReportResponse:
    """Convert a TrainingReport ORM model to a response schema."""
    # Parse model_metrics JSON into structured list
    metrics_list: list[ModelMetricsResponse] = []
    raw_metrics = report.model_metrics or {}

    # Handle both dict-of-dicts format ({"XGBoost": {...}}) and flat format
    for model_name, metrics in raw_metrics.items():
        if isinstance(metrics, dict):
            metrics_list.append(
                ModelMetricsResponse(
                    model_name=model_name,
                    rmse=metrics.get("rmse"),
                    mae=metrics.get("mae"),
                    accepted=metrics.get("accepted", False),
                    error=metrics.get("error"),
                )
            )

    return TrainingReportResponse(
        id=report.id,
        triggered_by=report.triggered_by,
        trigger_reason=report.trigger_reason,
        status=report.status,
        training_samples=report.training_samples or 0,
        test_samples=report.test_samples or 0,
        date_range_start=(
            report.date_range_start.isoformat() if report.date_range_start else None
        ),
        date_range_end=(
            report.date_range_end.isoformat() if report.date_range_end else None
        ),
        model_metrics=metrics_list,
        weights_before=report.weights_before,
        weights_after=report.weights_after,
        source_weights_before=report.source_weights_before,
        source_weights_after=report.source_weights_after,
        brier_score_before=report.brier_score_before,
        brier_score_after=report.brier_score_after,
        duration_seconds=report.duration_seconds or 0.0,
        completed_at=(
            report.completed_at.isoformat() if report.completed_at else ""
        ),
    )


@router.get("/reports", response_model=TrainingReportListResponse)
async def get_training_reports(
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrainingReportListResponse:
    """Get paginated training report history, newest first."""
    # Count total
    total_result = await db.execute(
        select(func.count()).select_from(TrainingReport)
    )
    total = total_result.scalar() or 0

    # Fetch page
    result = await db.execute(
        select(TrainingReport)
        .order_by(TrainingReport.completed_at.desc())
        .offset(offset)
        .limit(limit)
    )
    reports = result.scalars().all()

    return TrainingReportListResponse(
        reports=[_report_to_response(r) for r in reports],
        total=total,
    )


@router.post("/trigger", response_model=UpdateTriggerResponse)
async def trigger_retraining(
    user: User = Depends(get_current_user),
) -> UpdateTriggerResponse:
    """Manually trigger model retraining.

    Dispatches the train_all_models Celery task with triggered_by="manual".
    Returns immediately — the training runs asynchronously.
    """
    from backend.prediction.train_models import train_all_models

    train_all_models.delay(triggered_by="manual", trigger_reason="user_requested")

    logger.info("Manual retraining triggered by user")

    return UpdateTriggerResponse(
        status="dispatched",
        message="Model retraining has been triggered and will run in the background.",
    )

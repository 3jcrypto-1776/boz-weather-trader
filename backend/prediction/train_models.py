"""Multi-model training pipeline (Celery task) with training report persistence.

Queries historical forecast-vs-settlement data from the database, engineers
features, and trains all ML models (XGBoost, Random Forest, Ridge).
Computes inverse-RMSE weights and saves accepted models to disk.
Persists a TrainingReport record for the frontend Training Log.

Run manually:
    from backend.prediction.train_models import train_all_models
    train_all_models.apply()

Scheduled: Sunday 3 AM ET via Celery Beat (see celery_app.py).
Also triggered post-settlement when conditions are met (see scheduler.py).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from asgiref.sync import async_to_sync

from backend.celery_app import celery_app
from backend.common.config import get_settings
from backend.common.logging import get_logger
from backend.common.metrics import (
    ML_RETRAIN_TRIGGERS_TOTAL,
    ML_SOURCE_WEIGHTS_UPDATED_TOTAL,
    ML_TRAINING_DURATION_SECONDS,
)
from backend.prediction.features import NUM_FEATURES
from backend.prediction.model_ensemble import MultiModelEnsemble
from backend.prediction.train_xgb import _fetch_training_data, _rows_to_arrays

logger = get_logger("MODEL")


async def _get_avg_brier_score(session) -> float | None:  # noqa: ANN001
    """Compute average Brier score across all 4 cities.

    Returns None if insufficient data for any meaningful calculation.
    """
    from backend.prediction.calibration import check_calibration

    scores: list[float] = []
    for city in ["NYC", "CHI", "MIA", "AUS"]:
        try:
            report = await check_calibration(city, session, lookback_days=90)
            if report.status == "ok" and report.brier_score is not None:
                scores.append(report.brier_score)
        except Exception:
            continue

    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


async def _train_all_async(
    triggered_by: str = "schedule",
    trigger_reason: str | None = None,
) -> dict:
    """Async training logic — fetches data, trains models, persists report.

    Returns:
        Training metrics dict, or dict with status="skipped"/"error".
    """
    from backend.common.database import async_session, reset_engine
    from backend.common.models import TrainingReport
    from backend.prediction.source_weights import (
        compute_source_weights_from_accuracy,
        load_source_weights,
        save_source_weights,
    )

    # Reset the async engine so it is recreated in THIS event loop.
    # async_to_sync creates a fresh loop per Celery task invocation; the
    # singleton engine from a previous loop causes "Future attached to a
    # different loop" errors.
    reset_engine()

    settings = get_settings()
    started_at = datetime.now(UTC).replace(tzinfo=None)
    train_start = time.monotonic()

    async with async_session() as session:
        # ── Step 1: Capture "before" state ──
        ensemble = MultiModelEnsemble(model_dir=settings.xgb_model_dir)
        ensemble.load_all()
        weights_before = dict(ensemble.weights) if ensemble.weights else None

        source_weights_before = load_source_weights(settings.xgb_model_dir)
        brier_before = await _get_avg_brier_score(session)

        # ── Step 2: Fetch training data ──
        rows = await _fetch_training_data(session)

        if len(rows) < settings.xgb_min_training_samples:
            logger.info(
                "Insufficient training data for ML models",
                extra={
                    "data": {
                        "row_count": len(rows),
                        "min_required": settings.xgb_min_training_samples,
                    }
                },
            )
            # Persist a "skipped" report
            report = TrainingReport(
                triggered_by=triggered_by,
                trigger_reason=trigger_reason,
                status="skipped",
                training_samples=0,
                test_samples=0,
                model_metrics={"reason": "insufficient_data", "row_count": len(rows)},
                weights_before=weights_before,
                source_weights_before=source_weights_before,
                brier_score_before=brier_before,
                duration_seconds=round(time.monotonic() - train_start, 2),
                started_at=started_at,
                error_message=(
                    f"Only {len(rows)} samples (need {settings.xgb_min_training_samples})"
                ),
            )
            session.add(report)
            await session.commit()
            return {
                "status": "skipped",
                "reason": "insufficient_data",
                "row_count": len(rows),
                "report_id": report.id,
            }

        X, y = _rows_to_arrays(rows)  # noqa: N806

        if X.shape[1] != NUM_FEATURES:
            logger.error(
                "Feature count mismatch in training data",
                extra={"data": {"expected": NUM_FEATURES, "got": X.shape[1]}},
            )
            report = TrainingReport(
                triggered_by=triggered_by,
                trigger_reason=trigger_reason,
                status="error",
                model_metrics={"reason": "feature_mismatch"},
                weights_before=weights_before,
                source_weights_before=source_weights_before,
                brier_score_before=brier_before,
                duration_seconds=round(time.monotonic() - train_start, 2),
                started_at=started_at,
                error_message=f"Expected {NUM_FEATURES} features, got {X.shape[1]}",
            )
            session.add(report)
            await session.commit()
            return {
                "status": "error",
                "reason": "feature_mismatch",
                "report_id": report.id,
            }

        # ── Step 3: Chronological split + train ──
        split_idx = int(len(X) * 0.8)
        x_train, x_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]

        # Compute date range from training data
        date_range_start = rows[0].get("forecast_date") if rows else None
        date_range_end = rows[-1].get("forecast_date") if rows else None

        ensemble = MultiModelEnsemble(model_dir=settings.xgb_model_dir)
        result = ensemble.train_all(x_train, y_train, x_test, y_test)
        ensemble.save_all()

        weights_after = dict(ensemble.weights) if ensemble.weights else None

        # ── Step 4: Compute new source weights from accuracy data ──
        try:
            new_source_weights = await compute_source_weights_from_accuracy(session)
            save_source_weights(new_source_weights, settings.xgb_model_dir)
            ML_SOURCE_WEIGHTS_UPDATED_TOTAL.inc()
            source_weights_after = new_source_weights
        except Exception:
            logger.warning(
                "Source weight computation failed — keeping existing weights",
                exc_info=True,
            )
            source_weights_after = source_weights_before

        # ── Step 5: Capture "after" Brier score ──
        brier_after = await _get_avg_brier_score(session)

        # ── Step 6: Invalidate pipeline caches ──
        try:
            from backend.prediction.pipeline import reload_models

            reload_models()
        except Exception:
            logger.warning("Failed to invalidate pipeline caches", exc_info=True)

        # ── Step 7: Persist TrainingReport ──
        duration = round(time.monotonic() - train_start, 2)
        report = TrainingReport(
            triggered_by=triggered_by,
            trigger_reason=trigger_reason,
            status="completed",
            training_samples=len(x_train),
            test_samples=len(x_test),
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            model_metrics=result.get("models", {}),
            weights_before=weights_before,
            weights_after=weights_after,
            source_weights_before=source_weights_before,
            source_weights_after=source_weights_after,
            brier_score_before=brier_before,
            brier_score_after=brier_after,
            duration_seconds=duration,
            started_at=started_at,
        )
        session.add(report)
        await session.commit()

        result["status"] = "completed"
        result["row_count"] = len(rows)
        result["report_id"] = report.id
        return result


@celery_app.task(
    bind=True,
    name="backend.prediction.train_models.train_all_models",
    soft_time_limit=600,
    time_limit=720,
)
def train_all_models(
    self,  # noqa: ANN001
    triggered_by: str = "schedule",
    trigger_reason: str | None = None,
) -> dict:
    """Celery task: Train all ML models on historical forecast vs. settlement data.

    Scheduled weekly via Celery Beat. Also triggered post-settlement when
    accuracy conditions are met, or manually via the API.

    Args:
        triggered_by: Who initiated this ("schedule", "settlement", "manual").
        trigger_reason: Specific reason (e.g., "weekly", "settlement_count_25").
    """
    start = time.monotonic()

    try:
        ML_RETRAIN_TRIGGERS_TOTAL.labels(
            triggered_by=triggered_by,
            reason=trigger_reason or "unknown",
        ).inc()

        result = async_to_sync(_train_all_async)(triggered_by, trigger_reason)

        duration = time.monotonic() - start
        ML_TRAINING_DURATION_SECONDS.observe(duration)

        logger.info(
            "Multi-model training task completed",
            extra={"data": {"duration_s": round(duration, 1), "result": result}},
        )

        return result

    except Exception as exc:
        duration = time.monotonic() - start
        ML_TRAINING_DURATION_SECONDS.observe(duration)
        error_msg = str(exc)

        # Try to persist an error report
        try:
            from backend.common.database import async_session
            from backend.common.models import TrainingReport

            async def _save_error_report() -> None:
                from backend.common.database import reset_engine as _reset

                _reset()
                async with async_session() as session:
                    report = TrainingReport(
                        triggered_by=triggered_by,
                        trigger_reason=trigger_reason,
                        status="error",
                        model_metrics={},
                        duration_seconds=round(duration, 2),
                        started_at=datetime.now(UTC).replace(tzinfo=None),
                        error_message=error_msg,
                    )
                    session.add(report)
                    await session.commit()

            async_to_sync(_save_error_report)()
        except Exception:
            logger.warning("Failed to persist error training report")

        logger.error(
            "Multi-model training task failed",
            extra={"data": {"error": error_msg, "duration_s": round(duration, 1)}},
        )
        raise

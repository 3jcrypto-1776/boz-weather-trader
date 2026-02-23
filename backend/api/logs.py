"""Log viewer endpoint.

Provides filtered access to structured log entries stored in the
database, supporting module, level, and timestamp filters.

The frontend uses friendly module names (WEATHER, PREDICTION, TRADING,
SYSTEM, API) which map to one or more backend module tags.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.response_schemas import LogEntryResponse
from backend.common.database import get_db
from backend.common.logging import get_logger
from backend.common.models import LogEntry, User

logger = get_logger("API")

router = APIRouter()

MAX_LOG_ENTRIES = 200

# Map frontend-friendly module names → actual backend module tags.
# The frontend filter buttons use these keys; the backend loggers
# use more granular tags (e.g., ORDER, RISK under "TRADING").
MODULE_TAG_MAP: dict[str, list[str]] = {
    "WEATHER": ["WEATHER"],
    "PREDICTION": ["MODEL"],
    "TRADING": ["TRADING", "ORDER", "RISK", "COOLDOWN", "SETTLE", "POSTMORTEM"],
    "SYSTEM": ["SYSTEM", "AUTH", "MARKET"],
    "API": ["API"],
}


@router.get("", response_model=list[LogEntryResponse])
async def get_logs(
    module: str | None = None,
    level: str | None = None,
    after: datetime | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LogEntryResponse]:
    """Fetch structured log entries with optional filters.

    Args:
        module: Optional module filter (WEATHER, PREDICTION, TRADING,
                SYSTEM, API). Mapped to backend tags via MODULE_TAG_MAP.
        level: Optional log level filter (INFO, WARNING, ERROR).
        after: Optional timestamp filter -- only logs after this time.
        user: The authenticated user (required for access control).
        db: Async database session.

    Returns:
        List of LogEntryResponse objects, ordered oldest-first (newest
        at bottom for the auto-scrolling log viewer), limited to
        MAX_LOG_ENTRIES most recent entries.
    """
    query = select(LogEntry)

    # Apply optional module filter with tag mapping
    if module is not None:
        tags = MODULE_TAG_MAP.get(module, [module])
        if len(tags) == 1:
            query = query.where(LogEntry.module_tag == tags[0])
        else:
            query = query.where(LogEntry.module_tag.in_(tags))

    if level is not None:
        query = query.where(LogEntry.level == level)

    if after is not None:
        query = query.where(LogEntry.timestamp > after)

    # Get the most recent entries (DESC), then reverse for display
    # so newest entries appear at the bottom (auto-scroll target)
    query = query.order_by(LogEntry.timestamp.desc()).limit(MAX_LOG_ENTRIES)

    result = await db.execute(query)
    entries = list(result.scalars().all())
    entries.reverse()  # Oldest first → newest at bottom

    return [
        LogEntryResponse(
            id=entry.id,
            timestamp=entry.timestamp,
            level=entry.level,
            module=entry.module_tag,
            message=entry.message,
            data=entry.data,
        )
        for entry in entries
    ]

"""Redis pub/sub subscribers for WebSocket events and log persistence.

Two subscribers run as asyncio.Tasks during FastAPI app lifespan:

1. redis_subscriber — bridges boz:events to WebSocket clients
2. log_subscriber — persists boz:log_entries to the log_entries DB table

Both handle Redis disconnection with exponential backoff reconnection.

Usage:
    from backend.websocket.subscriber import redis_subscriber, log_subscriber
    from backend.websocket.manager import manager

    task1 = asyncio.create_task(redis_subscriber(manager))
    task2 = asyncio.create_task(log_subscriber())
"""

from __future__ import annotations

import asyncio
import json

import redis.asyncio as aioredis

from backend.common.config import get_settings
from backend.common.logging import get_logger
from backend.common.metrics import WS_EVENTS_RECEIVED_TOTAL
from backend.websocket.events import EVENTS_CHANNEL, LOG_ENTRIES_CHANNEL
from backend.websocket.manager import ConnectionManager

logger = get_logger("SYSTEM")

MAX_BACKOFF_SECONDS = 30

# Maximum log entries to keep in the DB (oldest trimmed on each write batch)
MAX_LOG_ENTRIES_DB = 5000


async def redis_subscriber(mgr: ConnectionManager) -> None:
    """Subscribe to Redis boz:events and forward to WebSocket clients.

    Runs as a long-lived background task. On Redis disconnect, retries
    with exponential backoff up to MAX_BACKOFF_SECONDS.

    Args:
        mgr: The ConnectionManager to broadcast messages through.
    """
    attempt = 0

    while True:
        try:
            settings = get_settings()
            r = aioredis.from_url(settings.redis_url)
            pubsub = r.pubsub()
            await pubsub.subscribe(EVENTS_CHANNEL)

            logger.info(
                "Redis subscriber connected",
                extra={"data": {"channel": EVENTS_CHANNEL}},
            )
            attempt = 0  # Reset backoff on successful connect

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                # Increment metrics by event type
                try:
                    parsed = json.loads(data)
                    event_type = parsed.get("type", "unknown")
                    WS_EVENTS_RECEIVED_TOTAL.labels(event_type=event_type).inc()
                except (json.JSONDecodeError, AttributeError):
                    pass

                await mgr.broadcast(data)

        except asyncio.CancelledError:
            logger.info("Redis subscriber shutting down")
            break

        except Exception as exc:
            wait = min(2**attempt, MAX_BACKOFF_SECONDS)
            logger.warning(
                "Redis subscriber error, reconnecting",
                extra={
                    "data": {
                        "error": str(exc),
                        "attempt": attempt + 1,
                        "wait_seconds": wait,
                    }
                },
            )
            attempt += 1
            await asyncio.sleep(wait)


async def log_subscriber() -> None:
    """Subscribe to Redis boz:log_entries and persist to the database.

    Picks up log entries published by the DatabaseLogHandler (from any
    process — Celery workers, FastAPI, etc.) and writes them to the
    log_entries table. This powers the /logs frontend viewer.

    Runs as a long-lived background task in the FastAPI process.
    Handles Redis disconnection with exponential backoff.
    """
    from backend.common.database import get_task_session
    from backend.common.models import LogEntry

    attempt = 0

    while True:
        try:
            settings = get_settings()
            r = aioredis.from_url(settings.redis_url)
            pubsub = r.pubsub()
            await pubsub.subscribe(LOG_ENTRIES_CHANNEL)
            attempt = 0  # Reset backoff on successful connect

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                raw = message["data"]
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")

                try:
                    parsed = json.loads(raw)
                    db = await get_task_session()
                    try:
                        entry = LogEntry(
                            level=parsed["level"],
                            module_tag=parsed["module_tag"],
                            message=parsed["message"],
                            data=parsed.get("data"),
                        )
                        db.add(entry)
                        await db.commit()
                    finally:
                        await db.close()
                except Exception:
                    pass  # Don't crash on individual entry failures

        except asyncio.CancelledError:
            break

        except Exception:
            wait = min(2**attempt, MAX_BACKOFF_SECONDS)
            attempt += 1
            await asyncio.sleep(wait)

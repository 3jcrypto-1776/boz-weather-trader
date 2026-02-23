"""Structured logging setup for Boz Weather Trader.

Every log line includes: timestamp, level, module tag, message, and structured data.
Secrets are automatically redacted from log output.

INFO+ log entries are also published to Redis for database persistence.
The log_subscriber in the FastAPI process picks these up and writes to
the log_entries table, which powers the frontend log viewer at /logs.

Usage:
    from backend.common.logging import get_logger
    logger = get_logger("WEATHER")
    logger.info("Forecast fetched", extra={"data": {"city": "NYC", "temp_f": 56.3}})
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

import redis as sync_redis

# Module tags for structured logging
MODULE_TAGS = {
    "WEATHER",
    "MODEL",
    "MARKET",
    "TRADING",
    "ORDER",
    "RISK",
    "COOLDOWN",
    "AUTH",
    "SETTLE",
    "POSTMORTEM",
    "SYSTEM",
    "TEST",
    "API",
}

# Redis channel for log entry persistence
LOG_ENTRIES_CHANNEL = "boz:log_entries"

# Regex to find secret-looking values in JSON strings
_SECRET_KEY_PATTERN = re.compile(
    r'"([^"]*(?:key|secret|password|token|private|pem|credential)[^"]*)":\s*"([^"]*)"',
    re.IGNORECASE,
)


def _redact_secrets(text: str) -> str:
    """Replace values of secret-looking keys with [REDACTED] in a string."""
    return _SECRET_KEY_PATTERN.sub(r'"\1": "[REDACTED]"', text)


class StructuredFormatter(logging.Formatter):
    """Formats log records as structured, human-readable lines.

    Output format:
        2025-02-15T10:30:00Z | INFO | WEATHER | Forecast fetched | {"city": "NYC"}
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        level = record.levelname
        module_tag = getattr(record, "module_tag", "SYSTEM")

        # Include request ID when available (set by RequestIdMiddleware)
        try:
            from backend.common.middleware import request_id_var

            rid = request_id_var.get("")
        except ImportError:
            rid = ""

        # Extract structured data from extra
        data = getattr(record, "data", None)
        if data is not None:
            try:
                data_str = json.dumps(data, default=str)
                data_str = _redact_secrets(data_str)
            except (TypeError, ValueError):
                data_str = str(data)
        else:
            data_str = ""

        message = _redact_secrets(record.getMessage())

        parts = [timestamp, level]
        if rid:
            parts.append(f"rid={rid[:8]}")
        parts.extend([module_tag, message])
        if data_str:
            parts.append(data_str)

        return " | ".join(parts)


class ModuleTagLogger(logging.LoggerAdapter):
    """Logger adapter that injects module_tag and supports structured data.

    Usage:
        logger = get_logger("WEATHER")
        logger.info("Fetched forecast", extra={"data": {"city": "NYC"}})
    """

    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        # Inject module_tag into the record
        extra = kwargs.get("extra", {})
        extra["module_tag"] = self.extra.get("module_tag", "SYSTEM")
        kwargs["extra"] = extra
        return msg, kwargs


# ─── Sync Redis client for log persistence ───

_sync_redis_client: sync_redis.Redis | None = None
_sync_redis_unavailable: bool = False


def _get_sync_redis() -> sync_redis.Redis | None:
    """Lazy-init sync Redis client for log persistence.

    On first call, attempts to connect with a 200ms timeout. If Redis
    is unavailable, caches the failure so subsequent calls return None
    instantly (no blocking during tests or when Redis is down).
    """
    global _sync_redis_client, _sync_redis_unavailable
    if _sync_redis_unavailable:
        return None
    if _sync_redis_client is not None:
        return _sync_redis_client
    try:
        from backend.common.config import get_settings

        settings = get_settings()
        client = sync_redis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
        client.ping()  # Validate connection eagerly
        _sync_redis_client = client
        return _sync_redis_client
    except Exception:
        _sync_redis_unavailable = True
        return None


class DatabaseLogHandler(logging.Handler):
    """Publishes INFO+ log entries to Redis for DB persistence.

    Log entries published to the boz:log_entries channel are picked up
    by the log_subscriber in the FastAPI process and written to the
    log_entries database table, powering the /logs frontend viewer.

    Overrides handleError to suppress logging errors silently, so
    Redis failures never produce "--- Logging error ---" output.
    """

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < self.level:
            return  # Belt-and-suspenders level check (framework also checks)
        try:
            client = _get_sync_redis()
            if client is None:
                return
            entry = {
                "level": record.levelname,
                "module_tag": getattr(record, "module_tag", "SYSTEM"),
                "message": _redact_secrets(record.getMessage()),
                "data": getattr(record, "data", None),
            }
            client.publish(LOG_ENTRIES_CHANNEL, json.dumps(entry, default=str))
        except Exception:
            pass  # Never crash the app due to log persistence failure

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802
        """Suppress all logging errors from this handler silently."""
        pass


# Cache loggers to avoid duplicate handlers
_loggers: dict[str, ModuleTagLogger] = {}


def get_logger(module_tag: str) -> ModuleTagLogger:
    """Get a structured logger with the given module tag.

    Args:
        module_tag: One of the MODULE_TAGS (WEATHER, TRADING, ORDER, etc.)

    Returns:
        A logger adapter that injects the module tag into every log line.
        Includes both stdout formatting and Redis persistence (INFO+).
    """
    if module_tag in _loggers:
        return _loggers[module_tag]

    logger = logging.getLogger(f"boz.{module_tag.lower()}")

    # Only add handler if this logger doesn't have one yet
    if not logger.handlers:
        # Console output (all levels)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)

        # Database persistence via Redis (INFO+ only)
        db_handler = DatabaseLogHandler()
        db_handler.setLevel(logging.INFO)
        logger.addHandler(db_handler)

        logger.setLevel(logging.DEBUG)
        logger.propagate = False

    adapter = ModuleTagLogger(logger, {"module_tag": module_tag})
    _loggers[module_tag] = adapter
    return adapter


def reset_loggers() -> None:
    """Reset all cached loggers and Redis state. Used in tests."""
    global _loggers, _sync_redis_client, _sync_redis_unavailable
    _loggers.clear()
    _sync_redis_client = None
    _sync_redis_unavailable = False

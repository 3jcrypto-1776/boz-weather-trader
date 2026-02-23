"""Tests for structured logging setup."""

from __future__ import annotations

import io
import json
import logging
from unittest.mock import MagicMock, patch

from backend.common.logging import (
    LOG_ENTRIES_CHANNEL,
    DatabaseLogHandler,
    ModuleTagLogger,
    StructuredFormatter,
    _redact_secrets,
    get_logger,
)

# Counter for unique test logger names to avoid handler cache pollution
_test_logger_counter = 0


def _make_test_logger(module_tag: str) -> tuple[ModuleTagLogger, io.StringIO]:
    """Create an isolated logger + StringIO stream for output testing.

    Returns a (logger_adapter, stream) tuple. The logger writes to the
    in-memory stream, avoiding pytest capfd/capsys issues with cached
    Python logging handlers.
    """
    global _test_logger_counter
    _test_logger_counter += 1
    stream = io.StringIO()
    logger = logging.getLogger(f"boz.test_output_{_test_logger_counter}")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    adapter = ModuleTagLogger(logger, {"module_tag": module_tag})
    return adapter, stream


class TestGetLogger:
    """Test logger creation and configuration."""

    def test_returns_logger_adapter(self):
        """get_logger returns a ModuleTagLogger adapter."""
        logger = get_logger("TEST")
        assert logger is not None

    def test_same_tag_returns_same_logger(self):
        """Calling get_logger twice with same tag returns the same instance."""
        logger1 = get_logger("WEATHER")
        logger2 = get_logger("WEATHER")
        assert logger1 is logger2

    def test_different_tags_return_different_loggers(self):
        """Different tags produce different logger instances."""
        logger1 = get_logger("WEATHER")
        logger2 = get_logger("TRADING")
        assert logger1 is not logger2

    def test_log_output_contains_module_tag(self):
        """Log output includes the module tag."""
        logger, stream = _make_test_logger("ORDER")
        logger.info("Test message")
        assert "ORDER" in stream.getvalue()

    def test_log_output_contains_message(self):
        """Log output includes the message text."""
        logger, stream = _make_test_logger("SYSTEM")
        logger.info("System started")
        assert "System started" in stream.getvalue()

    def test_log_output_contains_level(self):
        """Log output includes the log level."""
        logger, stream = _make_test_logger("RISK")
        logger.warning("Risk limit approaching")
        assert "WARNING" in stream.getvalue()

    def test_structured_data_in_output(self):
        """Structured data dict appears in log output."""
        logger, stream = _make_test_logger("MARKET")
        logger.info("Market price", extra={"data": {"city": "NYC", "price": 22}})
        output = stream.getvalue()
        assert "NYC" in output
        assert "22" in output


class TestSecretRedaction:
    """Test that secrets are redacted from log output."""

    def test_redact_api_key(self):
        """Values for keys containing 'key' are redacted."""
        text = '{"api_key": "super-secret-123"}'
        redacted = _redact_secrets(text)
        assert "super-secret-123" not in redacted
        assert "[REDACTED]" in redacted

    def test_redact_private_key(self):
        """Values for keys containing 'private' are redacted."""
        text = '{"private_key": "-----BEGIN RSA PRIVATE KEY-----"}'
        redacted = _redact_secrets(text)
        assert "BEGIN RSA" not in redacted
        assert "[REDACTED]" in redacted

    def test_redact_password(self):
        """Values for keys containing 'password' are redacted."""
        text = '{"password": "hunter2"}'
        redacted = _redact_secrets(text)
        assert "hunter2" not in redacted

    def test_redact_token(self):
        """Values for keys containing 'token' are redacted."""
        text = '{"auth_token": "eyJhbGciOiJIUzI1NiJ9"}'
        redacted = _redact_secrets(text)
        assert "eyJhbG" not in redacted

    def test_non_secret_fields_preserved(self):
        """Non-secret fields are not redacted."""
        text = '{"city": "NYC", "temperature": "56"}'
        redacted = _redact_secrets(text)
        assert "NYC" in redacted
        assert "56" in redacted

    def test_secret_redaction_in_log_output(self):
        """Secrets in structured data are redacted in actual log output."""
        logger, stream = _make_test_logger("AUTH")
        logger.info(
            "Auth attempt",
            extra={"data": {"api_key": "real-secret-key-value", "city": "NYC"}},
        )
        output = stream.getvalue()
        assert "real-secret-key-value" not in output
        assert "NYC" in output


class TestDatabaseLogHandler:
    """Tests for the DatabaseLogHandler that publishes to Redis."""

    def _make_handler(self) -> DatabaseLogHandler:
        """Create a handler instance for testing."""
        import logging

        handler = DatabaseLogHandler()
        handler.setLevel(logging.INFO)
        return handler

    def _make_record(
        self,
        level: int = 20,  # INFO
        message: str = "Test message",
        module_tag: str = "TRADING",
        data: dict | None = None,
    ):
        """Create a logging.LogRecord with module_tag and data."""
        import logging

        record = logging.LogRecord(
            name="boz.trading",
            level=level,
            pathname="",
            lineno=0,
            msg=message,
            args=(),
            exc_info=None,
        )
        record.module_tag = module_tag
        if data is not None:
            record.data = data
        return record

    def test_publishes_info_to_redis(self):
        """Handler publishes INFO messages to Redis."""
        handler = self._make_handler()
        record = self._make_record(message="Trade executed")
        mock_redis = MagicMock()

        with patch("backend.common.logging._get_sync_redis", return_value=mock_redis):
            handler.emit(record)

        mock_redis.publish.assert_called_once()
        channel, payload = mock_redis.publish.call_args[0]
        assert channel == LOG_ENTRIES_CHANNEL
        parsed = json.loads(payload)
        assert parsed["level"] == "INFO"
        assert parsed["module_tag"] == "TRADING"
        assert parsed["message"] == "Trade executed"

    def test_skips_debug_messages(self):
        """Handler does not publish DEBUG messages."""
        import logging

        handler = self._make_handler()
        record = self._make_record(level=logging.DEBUG, message="Debug noise")
        mock_redis = MagicMock()

        with patch("backend.common.logging._get_sync_redis", return_value=mock_redis):
            handler.emit(record)

        mock_redis.publish.assert_not_called()

    def test_publishes_warning_and_error(self):
        """Handler publishes WARNING and ERROR messages."""
        import logging

        handler = self._make_handler()
        mock_redis = MagicMock()

        with patch("backend.common.logging._get_sync_redis", return_value=mock_redis):
            handler.emit(self._make_record(level=logging.WARNING, message="Warn"))
            handler.emit(self._make_record(level=logging.ERROR, message="Err"))

        assert mock_redis.publish.call_count == 2

    def test_includes_structured_data(self):
        """Handler includes structured data in the Redis payload."""
        handler = self._make_handler()
        record = self._make_record(data={"city": "AUS", "ev": 0.10})
        record.data = {"city": "AUS", "ev": 0.10}
        mock_redis = MagicMock()

        with patch("backend.common.logging._get_sync_redis", return_value=mock_redis):
            handler.emit(record)

        payload = json.loads(mock_redis.publish.call_args[0][1])
        assert payload["data"]["city"] == "AUS"
        assert payload["data"]["ev"] == 0.10

    def test_survives_redis_failure(self):
        """Handler catches Redis errors without raising."""
        handler = self._make_handler()
        record = self._make_record()
        mock_redis = MagicMock()
        mock_redis.publish.side_effect = ConnectionError("Redis down")

        with patch("backend.common.logging._get_sync_redis", return_value=mock_redis):
            # Should NOT raise
            handler.emit(record)

    def test_survives_no_redis_client(self):
        """Handler handles None Redis client gracefully."""
        handler = self._make_handler()
        record = self._make_record()

        with patch("backend.common.logging._get_sync_redis", return_value=None):
            # Should NOT raise
            handler.emit(record)

    def test_redacts_secrets_in_message(self):
        """Handler redacts secret-looking values in message text."""
        handler = self._make_handler()
        record = self._make_record(message='Login with {"api_key": "secret123"}')
        mock_redis = MagicMock()

        with patch("backend.common.logging._get_sync_redis", return_value=mock_redis):
            handler.emit(record)

        payload = json.loads(mock_redis.publish.call_args[0][1])
        assert "secret123" not in payload["message"]
        assert "[REDACTED]" in payload["message"]

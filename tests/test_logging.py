import io
import json
import logging

import pytest

from architect_ai.logging import JsonFormatter, configure_logging


def test_json_logging_allowlist_and_exception_redaction() -> None:
    record = logging.makeLogRecord(
        {
            "name": "architect_ai.test",
            "levelno": logging.ERROR,
            "levelname": "ERROR",
            "msg": "test.failed",
            "request_id": "request-123",
            "authorization": "Bearer secret",
        }
    )
    try:
        raise ValueError("private-project-data")
    except ValueError as exc:
        record.exc_info = (type(exc), exc, exc.__traceback__)
    serialized = JsonFormatter().format(record)
    data = json.loads(serialized)
    assert data["error_type"] == "ValueError"
    assert data["request_id"] == "request-123"
    assert "secret" not in serialized
    assert "private-project-data" not in serialized
    assert "authorization" not in data


def test_logging_configuration_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = io.StringIO()
    monkeypatch.setattr("sys.stderr", stream)
    configure_logging("INFO")
    configure_logging("INFO")
    logger = logging.getLogger("architect_ai")
    logger.info("test.once")
    assert len(stream.getvalue().splitlines()) == 1
    assert json.loads(stream.getvalue())["event"] == "test.once"

"""JSON event logging with explicit fields; never serialize arbitrary payloads."""

import json
import logging
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    """Format trusted event names and an allowlist of operational metadata."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key in ("request_id", "method", "status_code", "duration_ms"):
            value: object = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info and record.exc_info[0]:
            # Exception messages and tracebacks can contain credentials or project data.
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=True, allow_nan=False)


def configure_logging(level: str) -> None:
    """Configure only our logger; do not replace host/framework logging handlers."""
    logger = logging.getLogger("architect_ai")
    for handler in tuple(logger.handlers):
        if handler.get_name() == "architect_ai_json":
            logger.removeHandler(handler)
            handler.close()
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name("architect_ai_json")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

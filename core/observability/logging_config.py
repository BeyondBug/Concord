"""
core/observability/logging_config.py
Structured logging setup with correlation IDs.

Call ``configure_logging()`` once at startup. Two modes, chosen by
``CONCORD_LOG_FORMAT``:
  - ``json``  : one JSON object per line — timestamp, level, logger, message,
                and the current correlation_id. Suited to log aggregation.
  - anything else (default): human-readable text with the correlation id
                appended, for local development.

The correlation id is pulled from the request-scoped ContextVar, so every log
line emitted while handling a request carries that request's id — even lines
from deep in the orchestrator — without threading it through call signatures.
Log level is controlled by ``CONCORD_LOG_LEVEL`` (default INFO).
"""
from __future__ import annotations

import json
import logging
import os

from core.observability.correlation import get_correlation_id


class _CorrelationFilter(logging.Filter):
    """Attach the current correlation id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": getattr(record, "correlation_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    level = os.getenv("CONCORD_LOG_LEVEL", "INFO").upper()
    fmt = os.getenv("CONCORD_LOG_FORMAT", "text").lower()

    handler = logging.StreamHandler()
    handler.addFilter(_CorrelationFilter())
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [rid=%(correlation_id)s] "
            "%(message)s"
        ))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
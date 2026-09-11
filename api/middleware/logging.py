"""
api/middleware/logging.py
Request logging + correlation IDs.

Assigns every request a correlation ID (honoring an inbound ``X-Request-ID``
if the client supplies one), logs method/path/status/duration, and echoes the
ID back in the ``X-Request-ID`` response header so it can be surfaced in the
dashboard and CLI and traced through the audit log.

Secrets are never logged: only method, path, status, and duration are emitted.
"""
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from core.observability import reset_correlation_id, set_correlation_id

logger = logging.getLogger("concord.request")

_REQUEST_ID_HEADER = "X-Request-ID"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        raw_request_id = request.headers.get(_REQUEST_ID_HEADER, "")
        request_id = (
            raw_request_id
            if raw_request_id and len(raw_request_id) <= 128
            and raw_request_id.isascii()
            and all(ch.isalnum() or ch in "._:-" for ch in raw_request_id)
            else uuid.uuid4().hex[:16]
        )

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "rid=%s %s %s -> ERROR (%.1fms)",
                request_id, request.method, request.url.path, duration_ms,
            )
            raise
        finally:
            reset_correlation_id(token)

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "rid=%s %s %s -> %s (%.1fms)",
            request_id, request.method, request.url.path,
            response.status_code, duration_ms,
        )
        response.headers[_REQUEST_ID_HEADER] = request_id
        return response
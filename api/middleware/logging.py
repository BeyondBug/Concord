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

logger = logging.getLogger("concord.request")

_REQUEST_ID_HEADER = "X-Request-ID"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        request.state.request_id = request_id

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

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "rid=%s %s %s -> %s (%.1fms)",
            request_id, request.method, request.url.path,
            response.status_code, duration_ms,
        )
        response.headers[_REQUEST_ID_HEADER] = request_id
        return response
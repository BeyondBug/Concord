"""Concord FastAPI application."""
import pathlib
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse

from api.middleware.auth import auth_is_enforced, require_api_key
from api.middleware.logging import RequestLoggingMiddleware
from api.routes import audit, events, findings, scan
from core.observability.logging_config import configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the persistence backend once, at startup, so any Postgres
    # connection timeout happens here (before serving traffic) rather than
    # inside the first request that writes a finding.
    from core.persistence import get_store
    get_store()
    yield


app = FastAPI(title="Concord", version="0.1.0", lifespan=lifespan)

# Correlation IDs + request logging for every request.
app.add_middleware(RequestLoggingMiddleware)

# Public routers.
#   events.router  — includes /events/github, which is authenticated separately
#                    via HMAC signature verification (WEBHOOK_SECRET), and
#                    /events/demo for local review. Left key-free by design.
app.include_router(events.router)

# Protected routers — require the API key when one is configured
# (open dev mode when CONCORD_API_KEY is unset; see api/middleware/auth.py).
_protected = Depends(require_api_key)
app.include_router(findings.router, dependencies=[_protected])
app.include_router(audit.router, dependencies=[_protected])
app.include_router(scan.router, dependencies=[_protected])

_DASHBOARD = pathlib.Path(__file__).parent / "templates" / "dashboard.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    return HTMLResponse(content=_DASHBOARD.read_text(encoding="utf-8"))


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "concord",
        "version": "0.1.0",
        "auth_enforced": auth_is_enforced(),
    }
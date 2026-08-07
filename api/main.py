"""Concord FastAPI application — serves dashboard + API."""
import pathlib

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from api.routes import audit, events, findings

app = FastAPI(
    title="Concord",
    description="AI DevSecOps Orchestration Platform",
    version="0.1.0",
)

app.include_router(events.router)
app.include_router(findings.router)
app.include_router(audit.router)

_DASHBOARD = pathlib.Path(__file__).parent / "templates" / "dashboard.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    """Concord visual dashboard."""
    return HTMLResponse(content=_DASHBOARD.read_text(encoding="utf-8"))


@app.get("/health")
def health():
    return {"status": "ok", "service": "concord", "version": "0.1.0"}

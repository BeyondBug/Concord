"""Concord FastAPI application."""
from fastapi import FastAPI
from api.routes import events, findings, audit

app = FastAPI(
    title="Concord",
    description="AI DevSecOps Orchestration Platform",
    version="0.1.0",
)

app.include_router(events.router)
app.include_router(findings.router)
app.include_router(audit.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "concord", "version": "0.1.0"}

"""
api/routes/findings.py
Findings REST API backed by the persistent store (core.persistence).

``store`` is kept as a thin adapter with the historical method names
(``add``/``get``/``all``/``stats``) so existing callers such as
api/routes/scan.py keep working, but every call now reads and writes the
durable SQLite-backed store instead of an in-memory list.
"""
import os

from fastapi import APIRouter, HTTPException

from core.persistence import FindingRecord, get_store

router = APIRouter(prefix="/findings", tags=["findings"])


class _StoreAdapter:
    """Backwards-compatible facade over the durable persistence store."""

    def add(self, finding_id: str, severity: str, artifact: str,
            repo: str, source: str, path: str, result: dict) -> None:
        get_store().add_finding(FindingRecord(
            id=finding_id,
            severity=severity,
            artifact=artifact,
            repo=repo,
            source=source,
            path=path,
            agent=result.get("agent"),
            result=result,
        ))

    def all(self, limit: int = 50, severity: str | None = None,
            path: str | None = None) -> list:
        return get_store().list_findings(limit=limit, severity=severity, path=path)

    def get(self, finding_id: str) -> dict | None:
        return get_store().get_finding(finding_id)

    def stats(self) -> dict:
        return get_store().finding_stats()


store = _StoreAdapter()


@router.get("/")
async def list_findings(limit: int = 50, severity: str | None = None,
                        path: str | None = None):
    return {
        "findings": store.all(limit, severity=severity, path=path),
        "stats": store.stats(),
        "llm_provider": os.getenv("LLM_PROVIDER", "ollama"),
        "filters": {"severity": severity, "path": path},
    }


@router.get("/severity")
async def severity_breakdown():
    """Findings grouped by severity (for the Security view)."""
    return {"by_severity": get_store().severity_breakdown()}


@router.get("/incidents")
async def incidents(limit: int = 50):
    """Findings grouped by affected artifact into incident summaries."""
    inc = get_store().incidents(limit=limit)
    return {"incidents": inc, "total": len(inc)}


@router.get("/{finding_id}/detail")
async def finding_detail(finding_id: str):
    """A finding joined with its audit timeline (for the detail panel)."""
    s = get_store()
    f = s.get_finding(finding_id)
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    result = f.get("result", {})
    return {
        "finding": f,
        "agents": result.get("agents", {}),
        "auto_resolved": result.get("auto_resolved"),
        "approved_by": result.get("approved_by"),
        "rejected": result.get("rejected", False),
        "timeline": s.audit_for_finding(finding_id),
    }


@router.get("/{finding_id}")
async def get_finding(finding_id: str):
    f = store.get(finding_id)
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    return f
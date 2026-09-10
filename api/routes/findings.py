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

    def all(self, limit: int = 50) -> list:
        return get_store().list_findings(limit=limit)

    def get(self, finding_id: str) -> dict | None:
        return get_store().get_finding(finding_id)

    def stats(self) -> dict:
        return get_store().finding_stats()


store = _StoreAdapter()


@router.get("/")
async def list_findings(limit: int = 50):
    return {
        "findings": store.all(limit),
        "stats": store.stats(),
        "llm_provider": os.getenv("LLM_PROVIDER", "ollama"),
    }


@router.get("/{finding_id}")
async def get_finding(finding_id: str):
    f = store.get(finding_id)
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    return f
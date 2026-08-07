"""
api/routes/findings.py
In-memory findings store + REST API.
Phase 1: replace _FindingsStore with PostgreSQL.
"""
import os
import threading
from datetime import datetime

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/findings", tags=["findings"])


class _FindingsStore:
    """Thread-safe in-memory singleton. Replaced by PostgreSQL in Phase 1."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = []
        return cls._instance

    def add(self, finding_id: str, severity: str, artifact: str,
            repo: str, source: str, path: str, result: dict) -> None:
        with self._lock:
            self._data.insert(0, {
                "id": finding_id,
                "severity": severity,
                "artifact": artifact,
                "repo": repo,
                "source": source,
                "path": path,
                "agent": result.get("agent"),
                "result": result,
                "timestamp": datetime.utcnow().isoformat(),
            })
            self._data = self._data[:200]

    def all(self, limit: int = 50) -> list:
        with self._lock:
            return list(self._data[:limit])

    def get(self, finding_id: str) -> dict | None:
        with self._lock:
            return next((f for f in self._data if f["id"] == finding_id), None)

    def stats(self) -> dict:
        with self._lock:
            total = len(self._data)
            fast = sum(1 for f in self._data if f.get("path") == "fast_path")
            tiebreaks = sum(
                1 for f in self._data
                if f.get("result", {}).get("auto_resolved") is False
            )
            return {"total": total, "fast": fast,
                    "ai": total - fast, "tiebreaks": tiebreaks}


store = _FindingsStore()


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

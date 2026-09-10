"""
core/persistence/store.py
SQLite-backed persistence for findings and audit entries.

Why SQLite: the repo referenced PostgreSQL/Redis but nothing was wired up, so
finding storage was in-memory-only and audit was log-only. SQLite via the
stdlib gives real, durable, queryable persistence with zero external services,
and keeps the door open for a PostgreSQL backend later behind the same API.

Concurrency: a module-level lock serializes writes; connections use
``check_same_thread=False`` so the FastAPI thread pool and the orchestrator can
share one store instance. This is adequate for the current single-process
deployment. A PostgreSQL backend would replace this class wholesale.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("concord.persistence")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class FindingRecord:
    id: str
    severity: str
    artifact: str
    repo: str
    source: str
    path: str                       # "fast_path" | "ai_path"
    agent: str | None
    result: dict[str, Any]
    timestamp: str = field(default_factory=_utcnow)


@dataclass
class AuditRecord:
    finding_id: str
    path: str
    reason: str
    agent: str | None
    timestamp: str = field(default_factory=_utcnow)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    row_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    id        TEXT NOT NULL,
    severity  TEXT NOT NULL,
    artifact  TEXT NOT NULL,
    repo      TEXT NOT NULL DEFAULT '',
    source    TEXT NOT NULL DEFAULT '',
    path      TEXT NOT NULL,
    agent     TEXT,
    result    TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_id   ON findings(id);
CREATE INDEX IF NOT EXISTS idx_findings_path ON findings(path);

CREATE TABLE IF NOT EXISTS audit (
    row_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id TEXT NOT NULL,
    path       TEXT NOT NULL,
    reason     TEXT NOT NULL,
    agent      TEXT,
    timestamp  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_finding ON audit(finding_id);
"""


class SQLiteStore:
    """Durable finding + audit store. Safe for shared multi-thread use."""

    def __init__(self, db_path: str | None = None):
        self._path = db_path or os.getenv("CONCORD_DB_PATH", "concord.db")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self._path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        logger.info("SQLiteStore ready at %s", self._path)

    # ── Findings ──────────────────────────────────────────────────────

    def add_finding(self, record: FindingRecord) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO findings "
                "(id, severity, artifact, repo, source, path, agent, result, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id, record.severity, record.artifact, record.repo,
                    record.source, record.path, record.agent,
                    json.dumps(record.result), record.timestamp,
                ),
            )

    def list_findings(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM findings ORDER BY row_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._finding_row_to_dict(r) for r in rows]

    def get_finding(self, finding_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM findings WHERE id = ? ORDER BY row_id DESC LIMIT 1",
                (finding_id,),
            ).fetchone()
        return self._finding_row_to_dict(row) if row else None

    def finding_stats(self) -> dict[str, int]:
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM findings"
            ).fetchone()[0]
            fast = self._conn.execute(
                "SELECT COUNT(*) FROM findings WHERE path = 'fast_path'"
            ).fetchone()[0]
            rows = self._conn.execute(
                "SELECT result FROM findings WHERE path = 'ai_path'"
            ).fetchall()
        tiebreaks = sum(
            1 for r in rows
            if json.loads(r["result"]).get("auto_resolved") is False
        )
        return {"total": total, "fast": fast, "ai": total - fast,
                "tiebreaks": tiebreaks}

    # ── Audit ─────────────────────────────────────────────────────────

    def add_audit(self, record: AuditRecord) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit (finding_id, path, reason, agent, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (record.finding_id, record.path, record.reason,
                 record.agent, record.timestamp),
            )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        with self._lock:
            rows = self._conn.execute(
                "SELECT finding_id, path, reason, agent, timestamp "
                "FROM audit ORDER BY row_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Maintenance ───────────────────────────────────────────────────

    def clear(self) -> None:
        """Wipe all rows. Used by tests; never called in production paths."""
        with self._lock:
            self._conn.execute("DELETE FROM findings")
            self._conn.execute("DELETE FROM audit")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _finding_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d.pop("row_id", None)
        d["result"] = json.loads(d["result"])
        return d


# ── Module-level singleton accessor ───────────────────────────────────

_store_singleton: SQLiteStore | None = None
_singleton_lock = threading.Lock()


def get_store() -> SQLiteStore:
    """Return the process-wide store, creating it on first use."""
    global _store_singleton
    if _store_singleton is None:
        with _singleton_lock:
            if _store_singleton is None:
                _store_singleton = SQLiteStore()
    return _store_singleton


def _reset_store_for_tests(db_path: str = ":memory:") -> SQLiteStore:
    """Replace the singleton with a fresh in-memory store. Test-only."""
    global _store_singleton
    with _singleton_lock:
        if _store_singleton is not None:
            try:
                _store_singleton.close()
            except Exception:  # noqa: BLE001 - best-effort during teardown
                pass
        _store_singleton = SQLiteStore(db_path=db_path)
    return _store_singleton


__all__ = ["FindingRecord", "AuditRecord", "SQLiteStore", "get_store"]
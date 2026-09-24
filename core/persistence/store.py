"""
core/persistence/store.py
SQLite-backed persistence for findings and audit entries.

Why SQLite: the repo referenced PostgreSQL/Redis but nothing was wired up, so
finding storage was in-memory-only and audit was log-only. SQLite via the
stdlib gives real, durable, queryable persistence with zero external services,
and keeps the door open for a PostgreSQL backend later behind the same API.

Concurrency: a module-level lock serializes writes; connections use
``check_same_thread=False`` so the FastAPI thread pool and the orchestrator can
share one store instance. This is adequate for single-process deployments. For
multi-replica deployments, set CONCORD_DATABASE_URL to use the PostgreSQL
backend (core/persistence/postgres_store.py), which get_store() selects
automatically; SQLite remains the zero-dependency default and fallback.
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
    correlation_id: str = field(default_factory=lambda: _current_correlation_id())
    timestamp: str = field(default_factory=_utcnow)


def _current_correlation_id() -> str:
    # Imported lazily to avoid a hard import cycle at module load.
    from core.observability import get_correlation_id
    return get_correlation_id()


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
    correlation_id TEXT NOT NULL DEFAULT '-',
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
        self._migrate()
        logger.info("SQLiteStore ready at %s", self._path)

    def _migrate(self) -> None:
        """Additive migrations for databases created by an older schema."""
        cols = {row["name"] for row in
                self._conn.execute("PRAGMA table_info(audit)").fetchall()}
        if "correlation_id" not in cols:
            self._conn.execute(
                "ALTER TABLE audit ADD COLUMN correlation_id TEXT NOT NULL "
                "DEFAULT '-'"
            )
            logger.info("SQLiteStore: migrated audit table (correlation_id)")
        # Safe now that the column exists (fresh or migrated).
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_correlation "
            "ON audit(correlation_id)"
        )

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

    def list_findings(self, limit: int = 50, severity: str | None = None,
                      path: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        clauses, params = [], []
        if severity:
            clauses.append("severity = ?")
            params.append(severity.upper())
        if path:
            clauses.append("path = ?")
            params.append(path)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM findings{where} ORDER BY row_id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._finding_row_to_dict(r) for r in rows]

    def get_finding(self, finding_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM findings WHERE id = ? ORDER BY row_id DESC LIMIT 1",
                (finding_id,),
            ).fetchone()
        return self._finding_row_to_dict(row) if row else None

    def update_finding_result(self, finding_id: str,
                              result: dict[str, Any]) -> bool:
        """Replace the stored result JSON for the latest row of a finding.

        Returns True if a row was updated. Used by the approval flow to durably
        record that a human resolved a tiebreak — the previous code mutated a
        deserialized copy, which never reached storage.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT row_id FROM findings WHERE id = ? "
                "ORDER BY row_id DESC LIMIT 1", (finding_id,),
            ).fetchone()
            if row is None:
                return False
            self._conn.execute(
                "UPDATE findings SET result = ?, agent = ? WHERE row_id = ?",
                (json.dumps(result), result.get("agent"), row["row_id"]),
            )
            return True

    def list_pending_approvals(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return AI-path findings awaiting a human decision.

        A finding is pending when it took the ai_path, is not yet resolved
        (auto_resolved is False), and has not been approved.
        """
        limit = max(1, min(limit, 500))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM findings WHERE path = 'ai_path' "
                "ORDER BY row_id DESC LIMIT ?", (limit,),
            ).fetchall()
        pending = []
        for r in rows:
            d = self._finding_row_to_dict(r)
            res = d.get("result", {})
            if res.get("auto_resolved") is False and not res.get("approved_by"):
                pending.append(d)
        return pending

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

    def severity_breakdown(self) -> dict[str, int]:
        """Count findings grouped by severity (for the Security view)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT severity, COUNT(*) AS n FROM findings GROUP BY severity"
            ).fetchall()
        return {r["severity"]: r["n"] for r in rows}

    def incidents(self, limit: int = 50) -> list[dict[str, Any]]:
        """Group findings by affected artifact into incident summaries.

        An "incident" here is a real derivation: all findings touching the same
        artifact, with the count, the highest severity seen, and how many are
        still unresolved. No data is invented — empty when there are no findings.
        """
        limit = max(1, min(limit, 200))
        _rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1,
                 "INFORMATIONAL": 0}
        with self._lock:
            rows = self._conn.execute(
                "SELECT artifact, severity, path, result, timestamp "
                "FROM findings ORDER BY row_id DESC"
            ).fetchall()
        groups: dict[str, dict[str, Any]] = {}
        for r in rows:
            art = r["artifact"] or "(unknown)"
            g = groups.setdefault(art, {
                "artifact": art, "count": 0, "max_severity": "INFORMATIONAL",
                "unresolved": 0, "last_seen": r["timestamp"],
            })
            g["count"] += 1
            if _rank.get(r["severity"], 0) > _rank.get(g["max_severity"], 0):
                g["max_severity"] = r["severity"]
            res = json.loads(r["result"]) if r["result"] else {}
            if res.get("auto_resolved") is False and not res.get("approved_by"):
                g["unresolved"] += 1
        out = sorted(groups.values(),
                     key=lambda g: (-_rank.get(g["max_severity"], 0), -g["count"]))
        return out[:limit]

    # ── Audit ─────────────────────────────────────────────────────────

    def add_audit(self, record: AuditRecord) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit "
                "(finding_id, path, reason, agent, correlation_id, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (record.finding_id, record.path, record.reason,
                 record.agent, record.correlation_id, record.timestamp),
            )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        with self._lock:
            rows = self._conn.execute(
                "SELECT finding_id, path, reason, agent, correlation_id, timestamp "
                "FROM audit ORDER BY row_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def audit_for_finding(self, finding_id: str) -> list[dict[str, Any]]:
        """Audit entries for one finding, oldest first (a per-finding timeline)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT finding_id, path, reason, agent, correlation_id, timestamp "
                "FROM audit WHERE finding_id = ? ORDER BY row_id ASC",
                (finding_id,),
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

_store_singleton: Any | None = None
_singleton_lock = threading.Lock()


def _build_default_store():
    """Pick a backend: Postgres when configured + reachable, else SQLite.

    Selected by CONCORD_DATABASE_URL or POSTGRES_URL. Any connection failure
    falls back to SQLite and logs the downgrade, so a missing/broken Postgres
    never takes the platform down (fail-safe, matching the dedup store).
    """
    dsn = os.getenv("CONCORD_DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
    dsn = dsn.strip()
    if not dsn:
        return SQLiteStore()
    try:
        from core.persistence.postgres_store import PostgresStore
        store = PostgresStore(dsn)
        logger.info("Persistence backend: PostgreSQL")
        return store
    except Exception as exc:  # noqa: BLE001 - any failure → safe SQLite fallback
        logger.warning("PostgreSQL unavailable (%s); falling back to SQLite.", exc)
        return SQLiteStore()


def get_store():
    """Return the process-wide store, creating it on first use."""
    global _store_singleton
    if _store_singleton is None:
        with _singleton_lock:
            if _store_singleton is None:
                _store_singleton = _build_default_store()
    return _store_singleton


def _reset_store_for_tests(db_path: str = ":memory:") -> SQLiteStore:
    """Replace the singleton with a fresh in-memory SQLite store. Test-only."""
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
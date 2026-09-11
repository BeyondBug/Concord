"""
core/persistence/postgres_store.py
PostgreSQL-backed persistence, API-compatible with SQLiteStore.

Why: the Helm chart supports multiple replicas, but SQLite is single-process —
each pod would get its own database. PostgreSQL gives shared, durable storage
across replicas. Selected automatically by get_store() when CONCORD_DATABASE_URL
(or POSTGRES_URL) is set and reachable; otherwise the code falls back to SQLite,
so nothing breaks when Postgres is absent.

Uses psycopg 3 (sync) to match the store's synchronous method contract, which is
called from both sync FastAPI routes and the orchestrator. A small connection
pool is created per process; a module lock is unnecessary because psycopg
connections from the pool are checked out per call.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("concord.persistence.postgres")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    row_id    BIGSERIAL PRIMARY KEY,
    id        TEXT NOT NULL,
    severity  TEXT NOT NULL,
    artifact  TEXT NOT NULL,
    repo      TEXT NOT NULL DEFAULT '',
    source    TEXT NOT NULL DEFAULT '',
    path      TEXT NOT NULL,
    agent     TEXT,
    result    JSONB NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_id   ON findings(id);
CREATE INDEX IF NOT EXISTS idx_findings_path ON findings(path);

CREATE TABLE IF NOT EXISTS audit (
    row_id     BIGSERIAL PRIMARY KEY,
    finding_id TEXT NOT NULL,
    path       TEXT NOT NULL,
    reason     TEXT NOT NULL,
    agent      TEXT,
    correlation_id TEXT NOT NULL DEFAULT '-',
    timestamp  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_finding ON audit(finding_id);
"""


class PostgresStore:
    """Durable finding + audit store on PostgreSQL. API-compatible with SQLiteStore."""

    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 4):
        # Imported lazily so psycopg is only required when Postgres is used.
        from psycopg_pool import ConnectionPool

        # Bound the connection attempt so an unreachable server fails fast and
        # the caller can fall back to SQLite quickly instead of hanging.
        self._pool = ConnectionPool(
            dsn, min_size=min_size, max_size=max_size,
            kwargs={"autocommit": True, "connect_timeout": 3},
            timeout=5, open=False,
        )
        self._pool.open(wait=True, timeout=5)
        with self._pool.connection() as conn:
            conn.execute(_SCHEMA)
            # Additive migration for databases created by an older schema.
            conn.execute(
                "ALTER TABLE audit ADD COLUMN IF NOT EXISTS "
                "correlation_id TEXT NOT NULL DEFAULT '-'"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_correlation "
                "ON audit(correlation_id)"
            )
        logger.info("PostgresStore ready")

    # ── Findings ──────────────────────────────────────────────────────

    def add_finding(self, record) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO findings "
                "(id, severity, artifact, repo, source, path, agent, result, timestamp) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (record.id, record.severity, record.artifact, record.repo,
                 record.source, record.path, record.agent,
                 json.dumps(record.result), record.timestamp),
            )

    def list_findings(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, severity, artifact, repo, source, path, agent, "
                "result, timestamp FROM findings ORDER BY row_id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [self._finding_row(r) for r in rows]

    def get_finding(self, finding_id: str) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT id, severity, artifact, repo, source, path, agent, "
                "result, timestamp FROM findings WHERE id = %s "
                "ORDER BY row_id DESC LIMIT 1", (finding_id,),
            ).fetchone()
        return self._finding_row(row) if row else None

    def update_finding_result(self, finding_id: str,
                              result: dict[str, Any]) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT row_id FROM findings WHERE id = %s "
                "ORDER BY row_id DESC LIMIT 1", (finding_id,),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "UPDATE findings SET result = %s, agent = %s WHERE row_id = %s",
                (json.dumps(result), result.get("agent"), row[0]),
            )
            return True

    def list_pending_approvals(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, severity, artifact, repo, source, path, agent, "
                "result, timestamp FROM findings WHERE path = 'ai_path' "
                "ORDER BY row_id DESC LIMIT %s", (limit,),
            ).fetchall()
        pending = []
        for r in rows:
            d = self._finding_row(r)
            res = d.get("result", {})
            if res.get("auto_resolved") is False and not res.get("approved_by"):
                pending.append(d)
        return pending

    def severity_breakdown(self) -> dict[str, int]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT severity, COUNT(*) FROM findings GROUP BY severity"
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def finding_stats(self) -> dict[str, int]:
        with self._pool.connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
            fast = conn.execute(
                "SELECT COUNT(*) FROM findings WHERE path = 'fast_path'"
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT result FROM findings WHERE path = 'ai_path'"
            ).fetchall()
        tiebreaks = sum(1 for r in rows if _as_dict(r[0]).get("auto_resolved") is False)
        return {"total": total, "fast": fast, "ai": total - fast,
                "tiebreaks": tiebreaks}

    # ── Audit ─────────────────────────────────────────────────────────

    def add_audit(self, record) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO audit "
                "(finding_id, path, reason, agent, correlation_id, timestamp) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (record.finding_id, record.path, record.reason,
                 record.agent, record.correlation_id, record.timestamp),
            )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT finding_id, path, reason, agent, correlation_id, timestamp "
                "FROM audit ORDER BY row_id DESC LIMIT %s", (limit,),
            ).fetchall()
        return [{"finding_id": r[0], "path": r[1], "reason": r[2],
                 "agent": r[3], "correlation_id": r[4], "timestamp": r[5]}
                for r in rows]

    # ── Maintenance ───────────────────────────────────────────────────

    def clear(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM findings")
            conn.execute("DELETE FROM audit")

    def close(self) -> None:
        self._pool.close()

    @staticmethod
    def _finding_row(row) -> dict[str, Any]:
        return {
            "id": row[0], "severity": row[1], "artifact": row[2],
            "repo": row[3], "source": row[4], "path": row[5],
            "agent": row[6], "result": _as_dict(row[7]), "timestamp": row[8],
        }


def _as_dict(value) -> dict:
    """psycopg returns JSONB already-parsed; tolerate str too."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}
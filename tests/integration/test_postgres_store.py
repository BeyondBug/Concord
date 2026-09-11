"""Tests for the PostgreSQL backend selection and PostgresStore logic.

No live PostgreSQL server is required:
  - Backend selection / fallback is tested via env + monkeypatch.
  - PostgresStore's SQL and row-shaping logic is tested against a fake
    connection pool that records queries and returns canned rows.

A live-server integration test is out of scope for this environment (no
Postgres available); the operator can run one via docker-compose (see
docs/PROJECT_COMPLETION.md).
"""
import json

import pytest

from core.persistence import store as store_mod
from core.persistence.postgres_store import PostgresStore, _as_dict

# ── Backend selection / fallback ──────────────────────────────────────

def test_default_store_is_sqlite_without_dsn(monkeypatch):
    monkeypatch.delenv("CONCORD_DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    store = store_mod._build_default_store()
    from core.persistence.store import SQLiteStore
    assert isinstance(store, SQLiteStore)


def test_falls_back_to_sqlite_when_postgres_unreachable(monkeypatch):
    # Simulate an unreachable/broken Postgres by making construction raise,
    # then assert the factory degrades to SQLite rather than propagating.
    monkeypatch.setenv("CONCORD_DATABASE_URL",
                       "postgresql://x:y@127.0.0.1:1/nope")

    import core.persistence.postgres_store as pg

    def _boom(*a, **k):
        raise ConnectionError("cannot connect")

    monkeypatch.setattr(pg, "PostgresStore", _boom)
    store = store_mod._build_default_store()
    from core.persistence.store import SQLiteStore
    assert isinstance(store, SQLiteStore)


@pytest.mark.slow
def test_falls_back_on_real_unreachable_dsn(monkeypatch):
    # End-to-end fallback with a real (bounded) connection attempt. Marked slow
    # because it waits on the connect timeout; deselect with -m "not slow".
    monkeypatch.setenv("CONCORD_DATABASE_URL",
                       "postgresql://x:y@127.0.0.1:1/nope")
    store = store_mod._build_default_store()
    from core.persistence.store import SQLiteStore
    assert isinstance(store, SQLiteStore)


# ── Fake psycopg pool to exercise PostgresStore SQL logic ─────────────

class _FakeCursor:
    def __init__(self, result):
        self._result = result

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result


class _FakeConn:
    def __init__(self, recorder, canned):
        self._recorder = recorder
        self._canned = canned

    def execute(self, sql, params=None):
        self._recorder.append((sql, params))
        # Return canned rows keyed by a substring match of the SQL.
        for needle, rows in self._canned.items():
            if needle in sql:
                return _FakeCursor(rows)
        return _FakeCursor([])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakePool:
    def __init__(self, recorder, canned):
        self._recorder = recorder
        self._canned = canned

    def connection(self):
        return _FakeConn(self._recorder, self._canned)

    def close(self):
        pass


def _store_with(canned):
    """Build a PostgresStore whose __init__ pool creation is bypassed."""
    recorder: list = []
    store = PostgresStore.__new__(PostgresStore)  # skip real __init__
    store._pool = _FakePool(recorder, canned)     # type: ignore[attr-defined]
    return store, recorder


def test_add_finding_issues_insert():
    store, rec = _store_with({})

    class R:
        id, severity, artifact, repo, source = "F1", "HIGH", "a", "r", "s"
        path, agent, timestamp = "ai_path", "infra", "2026-01-01T00:00:00Z"
        result = {"path": "ai_path"}

    store.add_finding(R())
    sql, params = rec[0]
    assert "INSERT INTO findings" in sql
    assert params[0] == "F1"
    assert json.loads(params[7]) == {"path": "ai_path"}


def test_get_finding_shapes_row():
    row = ("F1", "HIGH", "a", "r", "s", "ai_path", "infra",
           {"path": "ai_path", "auto_resolved": False}, "2026-01-01T00:00:00Z")
    store, _ = _store_with({"WHERE id =": [row]})
    got = store.get_finding("F1")
    assert got["id"] == "F1"
    assert got["result"]["auto_resolved"] is False
    assert got["agent"] == "infra"


def test_update_finding_result_returns_false_when_absent():
    store, _ = _store_with({"SELECT row_id FROM findings": []})
    assert store.update_finding_result("ghost", {"x": 1}) is False


def test_update_finding_result_updates_when_present():
    store, rec = _store_with({"SELECT row_id FROM findings": [(42,)]})
    ok = store.update_finding_result("F1", {"agent": "infra", "auto_resolved": True})
    assert ok is True
    # last recorded call is the UPDATE with the row_id
    update_sql, params = rec[-1]
    assert "UPDATE findings SET result" in update_sql
    assert params[2] == 42


def test_list_pending_filters_unresolved():
    rows = [
        ("P", "HIGH", "a", "", "", "ai_path", "infra",
         {"auto_resolved": False}, "t"),
        ("R", "HIGH", "a", "", "", "ai_path", "infra",
         {"auto_resolved": True}, "t"),
        ("A", "HIGH", "a", "", "", "ai_path", "infra",
         {"auto_resolved": False, "approved_by": "infra"}, "t"),
    ]
    store, _ = _store_with({"WHERE path = 'ai_path'": rows})
    pending = store.list_pending_approvals()
    assert {p["id"] for p in pending} == {"P"}


def test_list_audit_shapes_rows():
    rows = [("F1", "fast_path", "low sev", None, "req-123", "t")]
    store, _ = _store_with({"FROM audit": rows})
    entries = store.list_audit()
    assert entries[0]["finding_id"] == "F1"
    assert entries[0]["reason"] == "low sev"
    assert entries[0]["correlation_id"] == "req-123"


# ── _as_dict helper ───────────────────────────────────────────────────

def test_as_dict_handles_dict_str_and_other():
    assert _as_dict({"a": 1}) == {"a": 1}
    assert _as_dict('{"a": 1}') == {"a": 1}
    assert _as_dict(None) == {}
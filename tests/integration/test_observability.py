"""Tests for correlation-ID propagation and structured logging (observability)."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from core.observability import (
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from core.observability.logging_config import _JsonFormatter, configure_logging
from core.persistence import AuditRecord, SQLiteStore
from core.persistence import store as store_mod

# ── ContextVar propagation ────────────────────────────────────────────

def test_default_correlation_is_dash():
    # No request active → sentinel.
    assert get_correlation_id() == "-"


def test_set_and_reset_correlation():
    token = set_correlation_id("req-abc")
    try:
        assert get_correlation_id() == "req-abc"
    finally:
        reset_correlation_id(token)
    assert get_correlation_id() == "-"


def test_empty_value_becomes_dash():
    token = set_correlation_id("")
    try:
        assert get_correlation_id() == "-"
    finally:
        reset_correlation_id(token)


# ── AuditRecord picks up the current correlation id ───────────────────

def test_audit_record_captures_correlation():
    token = set_correlation_id("req-xyz")
    try:
        rec = AuditRecord(finding_id="F1", path="fast_path",
                          reason="low", agent=None)
        assert rec.correlation_id == "req-xyz"
    finally:
        reset_correlation_id(token)


def test_audit_row_persists_correlation():
    store = SQLiteStore(db_path=":memory:")
    token = set_correlation_id("req-persist")
    try:
        store.add_audit(AuditRecord(finding_id="F1", path="fast_path",
                                    reason="low", agent=None))
    finally:
        reset_correlation_id(token)
    entries = store.list_audit()
    assert entries[0]["correlation_id"] == "req-persist"
    store.close()


# ── Migration: an old-schema DB gets the column added ─────────────────

def test_migration_adds_correlation_column(tmp_path):
    import sqlite3
    db = str(tmp_path / "old.db")
    # Create an audit table WITHOUT correlation_id, like an older build.
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE audit (row_id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "finding_id TEXT, path TEXT, reason TEXT, agent TEXT, "
                 "timestamp TEXT)")
    conn.execute("INSERT INTO audit (finding_id, path, reason, agent, timestamp) "
                 "VALUES ('OLD','fast_path','x',NULL,'t')")
    conn.commit()
    conn.close()

    # Opening with SQLiteStore should migrate it in place.
    store = SQLiteStore(db_path=db)
    entries = store.list_audit()
    assert entries[0]["finding_id"] == "OLD"
    assert entries[0]["correlation_id"] == "-"   # backfilled default
    store.close()


# ── JSON log formatter ────────────────────────────────────────────────

def test_json_formatter_includes_correlation():
    token = set_correlation_id("req-log")
    try:
        record = logging.LogRecord(
            name="concord.test", level=logging.INFO, pathname=__file__,
            lineno=1, msg="hello %s", args=("world",), exc_info=None)
        record.correlation_id = get_correlation_id()
        out = _JsonFormatter().format(record)
        parsed = json.loads(out)
        assert parsed["message"] == "hello world"
        assert parsed["correlation_id"] == "req-log"
        assert parsed["level"] == "INFO"
    finally:
        reset_correlation_id(token)


def test_configure_logging_json_mode(monkeypatch):
    monkeypatch.setenv("CONCORD_LOG_FORMAT", "json")
    configure_logging()
    root = logging.getLogger()
    assert root.handlers
    # restore default text formatting for other tests
    monkeypatch.setenv("CONCORD_LOG_FORMAT", "text")
    configure_logging()


# ── End-to-end: an API request stamps its id onto the audit rows ──────

@pytest.fixture
def client(monkeypatch):
    import importlib
    monkeypatch.delenv("CONCORD_API_KEY", raising=False)
    store_mod._reset_store_for_tests(":memory:")
    import api.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_request_id_flows_into_audit(client):
    # Drive a fast-path finding through the demo endpoint with a client-supplied
    # request id; the audit row it produces must carry that id.
    r = client.post("/events/demo?severity=LOW",
                    headers={"X-Request-ID": "trace-me-42"})
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == "trace-me-42"

    audit = store_mod.get_store().list_audit()
    assert any(a["correlation_id"] == "trace-me-42" for a in audit)


@pytest.fixture(autouse=True)
def _restore():
    yield
    import importlib

    import api.main as main_mod
    importlib.reload(main_mod)
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


def test_severity_endpoint(client):
    from core.persistence import FindingRecord
    for sev in ["CRITICAL", "HIGH", "HIGH"]:
        store_mod.get_store().add_finding(FindingRecord(
            id=f"SEV-{sev}-{id(object())}", severity=sev, artifact="x",
            repo="", source="", path="fast_path", agent=None, result={}))
    r = client.get("/findings/severity")
    assert r.status_code == 200
    bd = r.json()["by_severity"]
    assert bd["HIGH"] == 2
    assert bd["CRITICAL"] == 1


def test_version_endpoint(client):
    r = client.get("/version")
    assert r.status_code == 200
    assert r.json()["version"] == "0.1.0"


def test_dashboard_has_favicon(client):
    # The dashboard now embeds an inline SVG favicon (no more /favicon.ico 404).
    r = client.get("/")
    assert r.status_code == 200
    assert 'rel="icon"' in r.text


def test_agents_endpoint(client):
    r = client.get("/agents/")
    assert r.status_code == 200
    d = r.json()
    domains = {a["domain"]: a for a in d["agents"]}
    # Security must be active (it's a real agent), kubernetes planned.
    assert domains["security"]["status"] == "active"
    assert domains["kubernetes"]["status"] == "planned"
    assert d["active"] == 3
    assert d["planned"] == 2


def test_findings_severity_filter(client):
    from core.persistence import FindingRecord
    for sev in ["CRITICAL", "HIGH", "HIGH"]:
        store_mod.get_store().add_finding(FindingRecord(
            id=f"FL-{sev}-{id(object())}", severity=sev, artifact="x",
            repo="", source="", path="fast_path", agent=None, result={}))
    r = client.get("/findings/", params={"severity": "high"})
    assert r.status_code == 200
    body = r.json()
    assert body["filters"]["severity"] == "high"
    assert all(f["severity"] == "HIGH" for f in body["findings"])
    assert len(body["findings"]) == 2


def test_findings_path_filter(client):
    from core.persistence import FindingRecord
    store_mod.get_store().add_finding(FindingRecord(
        id="PF-fast", severity="LOW", artifact="x", repo="", source="",
        path="fast_path", agent=None, result={}))
    store_mod.get_store().add_finding(FindingRecord(
        id="PF-ai", severity="HIGH", artifact="x", repo="", source="",
        path="ai_path", agent="infra", result={}))
    r = client.get("/findings/", params={"path": "ai_path"})
    ids = {f["id"] for f in r.json()["findings"]}
    assert "PF-ai" in ids and "PF-fast" not in ids


def test_finding_detail_with_timeline(client):
    from core.persistence import AuditRecord, FindingRecord
    store_mod.get_store().add_finding(FindingRecord(
        id="D1", severity="HIGH", artifact="infra/main.tf", repo="r", source="s",
        path="ai_path", agent="infra",
        result={"auto_resolved": False, "agents": {"infra": 0.9, "cicd": 0.88}}))
    store_mod.get_store().add_audit(AuditRecord(
        finding_id="D1", path="ai_path", reason="human_tiebreak", agent="infra"))
    r = client.get("/findings/D1/detail")
    assert r.status_code == 200
    d = r.json()
    assert d["finding"]["id"] == "D1"
    assert d["agents"] == {"infra": 0.9, "cicd": 0.88}
    assert len(d["timeline"]) == 1
    assert d["timeline"][0]["reason"] == "human_tiebreak"


def test_finding_detail_404(client):
    assert client.get("/findings/ghost/detail").status_code == 404


def test_incidents_grouping(client):
    from core.persistence import FindingRecord
    # Two findings on the same artifact, one CRITICAL unresolved.
    store_mod.get_store().add_finding(FindingRecord(
        id="I1", severity="LOW", artifact="app/db.tf", repo="", source="",
        path="fast_path", agent=None, result={}))
    store_mod.get_store().add_finding(FindingRecord(
        id="I2", severity="CRITICAL", artifact="app/db.tf", repo="", source="",
        path="ai_path", agent="infra", result={"auto_resolved": False}))
    store_mod.get_store().add_finding(FindingRecord(
        id="I3", severity="HIGH", artifact="app/api.tf", repo="", source="",
        path="fast_path", agent=None, result={}))
    r = client.get("/findings/incidents")
    assert r.status_code == 200
    inc = {i["artifact"]: i for i in r.json()["incidents"]}
    assert inc["app/db.tf"]["count"] == 2
    assert inc["app/db.tf"]["max_severity"] == "CRITICAL"
    assert inc["app/db.tf"]["unresolved"] == 1
    # CRITICAL incident sorts first
    assert r.json()["incidents"][0]["artifact"] == "app/db.tf"
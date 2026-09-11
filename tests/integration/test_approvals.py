"""Tests for the approval flow: durable persistence, audit trail, pending list.

Regression coverage for the bug where approving a finding mutated a
deserialized copy that never reached storage and wrote nothing to the audit log.
"""

import pytest
from fastapi.testclient import TestClient

from core.persistence import FindingRecord, SQLiteStore
from core.persistence import store as store_mod


@pytest.fixture
def mem_store():
    s = SQLiteStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def client(monkeypatch):
    """App client with a fresh in-memory store and auth disabled (dev mode).

    Explicitly clears CONCORD_API_KEY so these tests are deterministic even
    when the surrounding shell has an API key set.
    """
    import importlib
    monkeypatch.delenv("CONCORD_API_KEY", raising=False)
    store_mod._reset_store_for_tests(":memory:")
    import api.main as main_mod
    import api.middleware.auth as auth_mod
    importlib.reload(auth_mod)
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


# ── Store-level behaviour ─────────────────────────────────────────────

def test_update_finding_result_persists(mem_store):
    mem_store.add_finding(FindingRecord(
        id="F-1", severity="HIGH", artifact="x", repo="", source="",
        path="ai_path", agent="infra",
        result={"path": "ai_path", "auto_resolved": False,
                "agents": {"infra": 0.9, "cicd": 0.88}}))
    ok = mem_store.update_finding_result(
        "F-1", {"path": "ai_path", "auto_resolved": True,
                "approved_by": "infra", "agent": "infra"})
    assert ok is True
    got = mem_store.get_finding("F-1")
    assert got["result"]["approved_by"] == "infra"
    assert got["result"]["auto_resolved"] is True
    assert got["agent"] == "infra"


def test_update_missing_finding_returns_false(mem_store):
    assert mem_store.update_finding_result("nope", {"x": 1}) is False


def test_list_pending_approvals_only_unresolved(mem_store):
    mem_store.add_finding(FindingRecord(
        id="PENDING", severity="HIGH", artifact="x", repo="", source="",
        path="ai_path", agent="infra",
        result={"auto_resolved": False, "agents": {"infra": 0.9}}))
    mem_store.add_finding(FindingRecord(
        id="RESOLVED", severity="HIGH", artifact="x", repo="", source="",
        path="ai_path", agent="infra",
        result={"auto_resolved": True}))
    mem_store.add_finding(FindingRecord(
        id="APPROVED", severity="HIGH", artifact="x", repo="", source="",
        path="ai_path", agent="infra",
        result={"auto_resolved": False, "approved_by": "infra"}))
    pending = mem_store.list_pending_approvals()
    ids = {p["id"] for p in pending}
    assert ids == {"PENDING"}


# ── API-level behaviour ───────────────────────────────────────────────

def _seed_tiebreak(finding_id="TB-1"):
    store_mod.get_store().add_finding(FindingRecord(
        id=finding_id, severity="HIGH", artifact="x", repo="r", source="s",
        path="ai_path", agent="infra",
        result={"path": "ai_path", "auto_resolved": False,
                "pr_comment": "needs human",
                "agents": {"infra": 0.9, "cicd": 0.88}}))


def test_approve_persists_and_audits(client):
    _seed_tiebreak("TB-1")
    r = client.post("/events/findings/TB-1/approve/infra")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["persisted"] is True

    # Durably resolved
    got = store_mod.get_store().get_finding("TB-1")
    assert got["result"]["approved_by"] == "infra"
    assert got["result"]["auto_resolved"] is True

    # Audit trail written
    audit = store_mod.get_store().list_audit()
    assert any(a["finding_id"] == "TB-1"
               and a["reason"] == "human_approved:infra" for a in audit)


def test_approve_unknown_finding_404(client):
    r = client.post("/events/findings/ghost/approve/infra")
    assert r.status_code == 404


def test_approve_non_candidate_agent_rejected(client):
    _seed_tiebreak("TB-2")
    r = client.post("/events/findings/TB-2/approve/kubernetes")
    assert r.status_code == 400
    assert "not a candidate" in r.json()["detail"]


def test_pending_approvals_endpoint(client):
    _seed_tiebreak("TB-3")
    r = client.get("/events/approvals/pending")
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()["pending"]}
    assert "TB-3" in ids

    # After approval it drops off the pending list.
    client.post("/events/findings/TB-3/approve/infra")
    r2 = client.get("/events/approvals/pending")
    ids2 = {p["id"] for p in r2.json()["pending"]}
    assert "TB-3" not in ids2


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    yield
    monkeypatch.delenv("CONCORD_API_KEY", raising=False)
    import importlib

    import api.main as main_mod
    import api.middleware.auth as auth_mod
    importlib.reload(auth_mod)
    importlib.reload(main_mod)
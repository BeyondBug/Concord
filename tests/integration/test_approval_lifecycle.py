"""Tests for the approval reject / expire flows."""
import importlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from core.persistence import FindingRecord
from core.persistence import store as store_mod


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("CONCORD_API_KEY", raising=False)
    store_mod._reset_store_for_tests(":memory:")
    import api.main as main_mod
    import api.middleware.auth as auth_mod
    importlib.reload(auth_mod)
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def _seed_pending(finding_id="TB", ts=None):
    store_mod.get_store().add_finding(FindingRecord(
        id=finding_id, severity="HIGH", artifact="x", repo="r", source="s",
        path="ai_path", agent="infra",
        result={"path": "ai_path", "auto_resolved": False,
                "agents": {"infra": 0.9, "cicd": 0.88}},
    ))
    if ts is not None:
        # overwrite timestamp for age-based tests
        s = store_mod.get_store()
        with s._lock:  # type: ignore[attr-defined]
            s._conn.execute("UPDATE findings SET timestamp = ? WHERE id = ?",
                            (ts, finding_id))


# ── Reject ────────────────────────────────────────────────────────────

def test_reject_marks_resolved_and_audits(client):
    _seed_pending("R1")
    r = client.post("/events/findings/R1/reject", params={"reason": "false positive"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    got = store_mod.get_store().get_finding("R1")
    assert got["result"]["rejected"] is True
    assert got["result"]["reject_reason"] == "false positive"

    audit = store_mod.get_store().list_audit()
    assert any("human_rejected" in a["reason"] for a in audit)


def test_reject_unknown_404(client):
    assert client.post("/events/findings/ghost/reject").status_code == 404


def test_rejected_finding_leaves_pending_queue(client):
    _seed_pending("R2")
    assert client.get("/events/approvals/pending").json()["total"] == 1
    client.post("/events/findings/R2/reject")
    assert client.get("/events/approvals/pending").json()["total"] == 0


# ── Expire ────────────────────────────────────────────────────────────

def test_expire_old_pending(client):
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    _seed_pending("OLD", ts=old)
    fresh = datetime.now(UTC).isoformat()
    _seed_pending("FRESH", ts=fresh)

    r = client.post("/events/approvals/expire", params={"max_age_hours": 24})
    assert r.status_code == 200
    body = r.json()
    assert "OLD" in body["expired"]
    assert "FRESH" not in body["expired"]
    assert body["count"] == 1

    # OLD is gone from pending, FRESH remains
    pending_ids = {p["id"] for p in
                   client.get("/events/approvals/pending").json()["pending"]}
    assert pending_ids == {"FRESH"}


def test_expire_audits_each(client):
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    _seed_pending("OLD2", ts=old)
    client.post("/events/approvals/expire", params={"max_age_hours": 24})
    audit = store_mod.get_store().list_audit()
    assert any("approval_expired" in a["reason"] and a["finding_id"] == "OLD2"
               for a in audit)


def test_expire_nothing_when_all_fresh(client):
    _seed_pending("F1", ts=datetime.now(UTC).isoformat())
    r = client.post("/events/approvals/expire", params={"max_age_hours": 24})
    assert r.json()["count"] == 0


@pytest.fixture(autouse=True)
def _restore():
    yield
    import api.main as main_mod
    importlib.reload(main_mod)
"""End-to-end test — the Friday demo scenario in automated form.

Owner: Both members. Run every Friday before the demo.
Flow: push webhook -> triage -> agents -> arbitration -> store + audit ->
human approval -> dashboard/CLI read paths. Everything runs for real in-process
(built-in scanners over tests/fixtures, SQLite in memory); only the external
kagent / HolmesGPT backends are absent, and the test asserts they are reported
as blocked rather than silently ignored.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("CONCORD_API_KEY", raising=False)
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    from api.main import app
    with TestClient(app) as c:
        yield c


def test_friday_demo_flow(client):
    # 1. A push webhook arrives for a commit touching Terraform.
    push = {
        "repository": {"full_name": "BeyondBug/CRMS"},
        "head_commit": {"id": "0123456789abcdef0123", "message": "open up IAM",
                        "modified": ["tests/fixtures/terraform"]},
    }
    r = client.post("/events/github", json=push, headers={"X-Request-ID": "e2e-1"})
    assert r.status_code == 202
    fid = r.json()["finding_id"]
    assert fid == "GH-0123456789ab"

    # 2. It was triaged, analyzed by the real agents and stored.
    f = client.get(f"/findings/{fid}").json()
    result = f["result"]
    assert f["path"] == "ai_path"
    assert set(result["agents"]) == {"infra", "cicd", "security"}
    # Deterministic confidence: HIGH (0.8) x reliability.
    assert result["agents"] == {"infra": 0.736, "cicd": 0.704, "security": 0.68}
    assert result["analyses"]["infra"]["violations"] > 0
    assert set(result["skipped_agents"]) == {"kubernetes", "observability"}
    assert result["needs_approval"] is True        # gap < 0.15 → human decides

    # 3. It shows up everywhere the dashboard and CLI read from.
    assert client.get("/findings/").json()["stats"]["tiebreaks"] == 1
    pending = client.get("/events/approvals/pending").json()["pending"]
    assert [p["id"] for p in pending] == [fid]
    audit = client.get("/audit/").json()["entries"]
    assert audit[0]["finding_id"] == fid and audit[0]["correlation_id"] == "e2e-1"
    agents = {a["domain"]: a["status"] for a in client.get("/agents/").json()["agents"]}
    assert agents["kubernetes"] == "blocked" and agents["infra"] == "active"

    # 4. A human approves the infra agent; the decision is durable and audited.
    r = client.post(f"/events/findings/{fid}/approve/infra")
    assert r.status_code == 200 and r.json()["persisted"] is True
    detail = client.get(f"/findings/{fid}/detail").json()
    assert detail["approved_by"] == "infra"
    assert [t["reason"] for t in detail["timeline"]] == ["human_tiebreak",
                                                         "human_approved:infra"]
    assert client.get("/events/approvals/pending").json()["total"] == 0

    # 5. The same push again is deduplicated: audited, no second finding.
    client.post("/events/github", json=push)
    assert client.get("/findings/").json()["stats"]["total"] == 1
    assert len(client.get(f"/findings/{fid}/detail").json()["timeline"]) == 3

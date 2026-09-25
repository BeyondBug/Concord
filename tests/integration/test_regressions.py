"""Regression tests for bugs found in the docs/AUDIT.md review (one per bug)."""
import asyncio
import subprocess
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from core.models.finding import Finding
from core.orchestrator.orchestrator import Orchestrator
from core.persistence import FindingRecord, get_store
from core.scanner import KubernetesScanner


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("CONCORD_API_KEY", raising=False)
    from api.main import app
    return TestClient(app, raise_server_exceptions=False)


def _finding(fid="R-1", severity="CRITICAL"):
    return Finding(id=fid, source="test", artifact="tests/fixtures/terraform",
                   severity=severity, title="t", description="d", raw={},
                   timestamp=datetime.now(UTC))


# ── Scanner false positives ───────────────────────────────────────────

def _k8s(tmp_path, text):
    (tmp_path / "m.yaml").write_text(text)
    return {f.check_id for f in KubernetesScanner().scan(str(tmp_path))}


def test_cap_check_ignores_the_word_all(tmp_path):
    ids = _k8s(tmp_path, "kind: ConfigMap\ndata:\n  note: install all the things\n")
    assert "CKV_K8S_28" not in ids


def test_cap_check_ignores_drop_all(tmp_path):
    ids = _k8s(tmp_path, "kind: Pod\nspec:\n  containers:\n  - securityContext:\n"
                         "      capabilities:\n        drop: [\"ALL\"]\n")
    assert "CKV_K8S_28" not in ids


@pytest.mark.parametrize("snippet", [
    "        add: [\"NET_ADMIN\"]\n",
    "        add:\n          - SYS_ADMIN\n",
])
def test_cap_check_flags_added_caps(tmp_path, snippet):
    ids = _k8s(tmp_path, "kind: Pod\nspec:\n  containers:\n  - securityContext:\n"
                         "      capabilities:\n" + snippet)
    assert "CKV_K8S_28" in ids


def test_probe_check_only_for_workloads(tmp_path):
    assert "CKV_K8S_8" not in _k8s(tmp_path, "kind: ConfigMap\ndata: {}\n")
    assert "CKV_K8S_8" in _k8s(tmp_path, "kind: Deployment\nspec: {}\n")


# ── Duplicate findings ────────────────────────────────────────────────

def test_list_shows_one_row_per_finding():
    store = get_store()
    for path in ("ai_path", "fast_path"):
        store.add_finding(FindingRecord(id="DUP", severity="HIGH", artifact="a",
                                        repo="", source="", path=path, agent=None,
                                        result={"path": path}))
    rows = store.list_findings()
    assert [r["id"] for r in rows] == ["DUP"]
    assert rows[0]["path"] == "fast_path"          # the latest decision
    assert store.finding_stats()["total"] == 1


async def test_repeated_finding_adds_no_duplicate_row():
    first = await Orchestrator().process(_finding())
    second = await Orchestrator().process(_finding())   # a new Orchestrator
    assert first["path"] == "ai_path"
    # The dedup store is shared per process, so the repeat fast-paths...
    assert second["path"] == "fast_path" and second["duplicate_of_existing"]
    # ...leaves the pending tiebreak as the current decision...
    assert get_store().get_finding("R-1")["path"] == "ai_path"
    assert len(get_store().list_findings()) == 1
    # ...and is still audited.
    reasons = [a["reason"] for a in get_store().audit_for_finding("R-1")]
    assert reasons[0] == "human_tiebreak" and "duplicate" in reasons[1]


async def test_ai_result_carries_candidates_for_approval():
    result = await Orchestrator().process(_finding())
    assert set(result["agents"]) == {"infra", "cicd", "security"}
    assert result["analyses"]["infra"]["violations"] > 0
    assert result["needs_approval"] is True


async def test_failing_agent_does_not_sink_the_pipeline():
    class Boom:
        domain = "infra"
        source_reliability = 0.9

        async def analyze(self, finding):
            raise RuntimeError("scanner crashed")

    class Slow:
        domain = "cicd"
        source_reliability = 0.88

        async def analyze(self, finding):
            await asyncio.sleep(0.01)
            from core.models.agent_response import AgentResponse
            return AgentResponse("cicd", finding.id, 0.0, "rc", "fix")

    result = await Orchestrator(agents=[Boom(), Slow()]).process(_finding("R-2"))
    assert result["agent"] == "cicd"
    assert result["skipped_agents"] == {"infra": "error: scanner crashed"}


async def test_no_agents_is_stored_and_audited():
    class Nope:
        domain = "infra"
        source_reliability = 0.9

        async def analyze(self, finding):
            raise NotImplementedError

    result = await Orchestrator(agents=[Nope()]).process(_finding("R-3"))
    assert result["error"] == "no agent responses"
    assert get_store().get_finding("R-3") is not None
    assert get_store().audit_for_finding("R-3")[0]["reason"] == "no_agent_responses"


# ── Approval state machine ────────────────────────────────────────────

def _pending(fid):
    get_store().add_finding(FindingRecord(
        id=fid, severity="HIGH", artifact="a", repo="", source="", path="ai_path",
        agent="infra", result={"path": "ai_path", "auto_resolved": False,
                               "agents": {"infra": 0.8, "cicd": 0.7}}))


def test_approve_twice_is_409(client):
    _pending("AP-1")
    assert client.post("/events/findings/AP-1/approve/infra").status_code == 200
    r = client.post("/events/findings/AP-1/approve/cicd")
    assert r.status_code == 409 and "already approved" in r.json()["detail"]


def test_reject_after_approve_is_409(client):
    _pending("AP-2")
    client.post("/events/findings/AP-2/approve/infra")
    assert client.post("/events/findings/AP-2/reject").status_code == 409


def test_approve_fast_path_finding_is_409(client):
    get_store().add_finding(FindingRecord(id="FP", severity="LOW", artifact="a",
                                          repo="", source="", path="fast_path",
                                          agent=None, result={"path": "fast_path"}))
    assert client.post("/events/findings/FP/approve/infra").status_code == 409


def test_rejected_finding_not_counted_as_tiebreak(client):
    _pending("AP-3")
    client.post("/events/findings/AP-3/reject")
    assert get_store().finding_stats()["tiebreaks"] == 0


# ── Input validation / error handling ─────────────────────────────────

def test_demo_rejects_unknown_severity(client):
    assert client.post("/events/demo", params={"severity": "BOGUS"}).status_code == 422


def test_findings_limit_validated(client):
    assert client.get("/findings/", params={"limit": 0}).status_code == 422
    assert client.get("/findings/", params={"path": "nope"}).status_code == 422


def test_webhook_bad_json_is_400(client, monkeypatch):
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    r = client.post("/events/github", content=b"{not json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_webhook_without_commit_is_ignored_not_invented(client, monkeypatch):
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    r = client.post("/events/github", json={"repository": {"full_name": "a/b"}})
    assert r.status_code == 202 and r.json()["status"] == "ignored"
    assert get_store().list_findings() == []


def test_demo_requires_key_when_enforced(monkeypatch):
    import importlib

    import api.main as main_mod
    import api.middleware.auth as auth_mod
    monkeypatch.setenv("CONCORD_API_KEY", "k-123")
    importlib.reload(auth_mod)
    importlib.reload(main_mod)
    try:
        c = TestClient(main_mod.app)
        assert c.post("/events/demo").status_code == 401
    finally:
        monkeypatch.delenv("CONCORD_API_KEY")
        importlib.reload(auth_mod)
        importlib.reload(main_mod)


def test_unhandled_error_is_json_with_request_id(client, monkeypatch):
    import core.persistence.store as store_mod

    def boom(*a, **k):
        raise RuntimeError("db exploded")
    monkeypatch.setattr(store_mod.SQLiteStore, "severity_breakdown", boom)
    r = client.get("/findings/severity", headers={"X-Request-ID": "rid-500"})
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal server error", "request_id": "rid-500"}


# ── Scan route ────────────────────────────────────────────────────────

@pytest.fixture
def scan_repo(tmp_path, monkeypatch):
    """A real local git repository used as the scan target."""
    src = tmp_path / "src"
    (src / "infra").mkdir(parents=True)
    (src / "infra" / "main.tf").write_text(
        'resource "aws_iam_policy" "p" {\n  policy = { Action = "*" }\n}\n')
    (src / "k8s").mkdir()
    (src / "k8s" / "deploy.yaml").write_text(
        "kind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n"
        "      - image: nginx:latest\n        securityContext:\n"
        "          privileged: true\n")
    for cmd in (["init", "-q"], ["add", "."],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"]):
        subprocess.run(["git", *cmd], cwd=src, check=True, capture_output=True)
    monkeypatch.setenv("CONCORD_SCAN_REPO_URL", str(src))
    monkeypatch.setenv("CONCORD_SCAN_REPO", "local/testrepo")
    monkeypatch.setenv("CONCORD_SCAN_DIR", str(tmp_path / "checkout"))
    import api.routes.scan as scan_mod
    monkeypatch.setattr(scan_mod, "_scan_state", scan_mod.ScanState())
    return scan_mod


def test_scan_clones_analyzes_and_is_idempotent(client, scan_repo):
    r = client.post("/events/scan-crms")
    assert r.status_code == 200
    st = client.get("/events/scan-status").json()
    assert st["status"] == "done", st
    assert st["finding_id"].startswith("TESTREPO-") and len(st["commit"]) == 40
    assert st["severity"] == "CRITICAL" and st["by_scanner"]["terraform"] >= 1
    assert st["needs_approval"] is True

    stored = get_store().get_finding(st["finding_id"])
    assert stored["result"]["scan"]["total"] == st["total"]
    assert stored["repo"] == "local/testrepo"

    # Second scan of the same commit: no new finding, audited as a re-scan.
    client.post("/events/scan-crms")
    again = client.get("/events/scan-status").json()
    assert again["unchanged"] is True and again["finding_id"] == st["finding_id"]
    assert len(get_store().list_findings()) == 1
    reasons = [a["reason"] for a in get_store().audit_for_finding(st["finding_id"])]
    assert reasons == ["human_tiebreak", f"rescan_unchanged:{st['commit'][:12]}"]


def test_scan_clone_failure_is_reported(client, scan_repo, monkeypatch, tmp_path):
    monkeypatch.setenv("CONCORD_SCAN_REPO_URL", str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("CONCORD_SCAN_DIR", str(tmp_path / "other-checkout"))
    client.post("/events/scan-crms")
    st = client.get("/events/scan-status").json()
    assert st["status"] == "error" and "git clone" in st["error"]


def test_scan_rejects_concurrent_trigger(client, scan_repo):
    scan_repo._scan_state.status = "scanning"
    assert client.post("/events/scan-crms").status_code == 409

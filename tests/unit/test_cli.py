"""Tests for the Concord CLI (concord_cli/main.py).

Uses Typer's CliRunner with the API helpers monkeypatched, so no live server is
needed. Covers table + JSON output, the pending/approve flow, and exit codes.
"""
import json

import httpx
import pytest
from typer.testing import CliRunner

import concord_cli.main as cli

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_color(monkeypatch):
    # Deterministic, decoration-free output for assertions.
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("CONCORD_OUTPUT", raising=False)


def test_version():
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert "Concord" in result.stdout


def test_health_table(monkeypatch):
    monkeypatch.setattr(cli, "_api_get",
                        lambda *a, **k: {"status": "ok", "version": "0.1.0",
                                         "auth_enforced": True})
    result = runner.invoke(cli.app, ["health"])
    assert result.exit_code == 0
    assert "ok" in result.stdout
    assert "enforced" in result.stdout


def test_health_json(monkeypatch):
    payload = {"status": "ok", "version": "0.1.0", "auth_enforced": False}
    monkeypatch.setattr(cli, "_api_get", lambda *a, **k: payload)
    result = runner.invoke(cli.app, ["health", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["status"] == "ok"
    assert parsed["auth_enforced"] is False


def test_findings_json(monkeypatch):
    payload = {
        "findings": [{"id": "F1", "severity": "HIGH", "path": "ai_path",
                      "agent": "infra", "artifact": "a/b.tf",
                      "timestamp": "2026-01-01"}],
        "stats": {"total": 1, "fast": 0, "ai": 1, "tiebreaks": 1},
    }
    monkeypatch.setattr(cli, "_api_get", lambda *a, **k: payload)
    result = runner.invoke(cli.app, ["findings", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["stats"]["total"] == 1


def test_findings_table(monkeypatch):
    payload = {"findings": [], "stats": {"total": 0}}
    monkeypatch.setattr(cli, "_api_get", lambda *a, **k: payload)
    result = runner.invoke(cli.app, ["findings"])
    assert result.exit_code == 0
    assert "No findings" in result.stdout


def test_audit_json(monkeypatch):
    payload = {"entries": [{"finding_id": "F1", "path": "fast_path",
                            "reason": "low", "agent": None,
                            "correlation_id": "req-1", "timestamp": "t"}],
               "total": 1}
    monkeypatch.setattr(cli, "_api_get", lambda *a, **k: payload)
    result = runner.invoke(cli.app, ["audit", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["total"] == 1


def test_approvals_empty(monkeypatch):
    monkeypatch.setattr(cli, "_api_get", lambda *a, **k: {"pending": [], "total": 0})
    result = runner.invoke(cli.app, ["approvals"])
    assert result.exit_code == 0
    assert "No approvals pending" in result.stdout


def test_approvals_list(monkeypatch):
    payload = {"pending": [{"id": "TB1", "severity": "HIGH",
                            "artifact": "a/b.tf",
                            "result": {"agents": {"infra": 0.9, "cicd": 0.88}}}],
               "total": 1}
    monkeypatch.setattr(cli, "_api_get", lambda *a, **k: payload)
    result = runner.invoke(cli.app, ["approvals"])
    assert result.exit_code == 0
    assert "awaiting approval" in result.stdout
    assert "infra" in result.stdout


def test_approve_success(monkeypatch):
    monkeypatch.setattr(cli, "_api_post",
                        lambda *a, **k: {"status": "approved", "persisted": True})
    result = runner.invoke(cli.app, ["approve", "TB1", "infra"])
    assert result.exit_code == 0
    assert "Approved" in result.stdout


def test_approve_rejected_sets_exit_code(monkeypatch):
    # Simulate the API returning 400 for a non-candidate agent.
    def _raise(*a, **k):
        req = httpx.Request("POST", "http://x/approve")
        resp = httpx.Response(400, json={"detail": "not a candidate"}, request=req)
        raise httpx.HTTPStatusError("400", request=req, response=resp)

    monkeypatch.setattr(cli, "_api_post", _raise)
    result = runner.invoke(cli.app, ["approve", "TB1", "kubernetes"])
    assert result.exit_code == 1


def test_unreachable_api_exit_code(monkeypatch):
    def _boom(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(cli, "_api_get", _boom)
    result = runner.invoke(cli.app, ["findings"])
    assert result.exit_code == 2  # distinct code for "API unreachable"


def test_agents_lists_active_and_planned(monkeypatch):
    payload = {"agents": [
        {"domain": "infra", "backing": "scan", "reliability": 0.92, "status": "active"},
        {"domain": "security", "backing": "scan", "reliability": 0.85, "status": "active"},
        {"domain": "kubernetes", "backing": "kagent", "reliability": 0.82, "status": "planned"},
    ], "active": 2, "planned": 1}
    monkeypatch.setattr(cli, "_api_get", lambda *a, **k: payload)
    result = runner.invoke(cli.app, ["agents"])
    assert result.exit_code == 0
    assert "infra" in result.stdout
    assert "security" in result.stdout


def test_stats_json(monkeypatch):
    def _get(path, params=None):
        if path == "/findings/":
            return {"stats": {"total": 5, "fast": 3, "ai": 2, "tiebreaks": 1}}
        if path.startswith("/events/approvals"):
            return {"total": 2}
        if path == "/audit/":
            return {"total": 9}
        return {}
    monkeypatch.setattr(cli, "_api_get", _get)
    result = runner.invoke(cli.app, ["stats", "--json"])
    assert result.exit_code == 0
    d = json.loads(result.stdout)
    assert d["total"] == 5
    assert d["pending_approvals"] == 2
    assert d["audit_events"] == 9


def test_reject_command(monkeypatch):
    monkeypatch.setattr(cli, "_api_post",
                        lambda *a, **k: {"status": "rejected", "finding_id": "F1"})
    result = runner.invoke(cli.app, ["reject", "F1"])
    assert result.exit_code == 0
    assert "Rejected" in result.stdout


def test_diagnostics_json_healthy(monkeypatch):
    monkeypatch.setattr(cli, "_api_get",
                        lambda *a, **k: {"status": "ok", "auth_enforced": False})
    result = runner.invoke(cli.app, ["diagnostics", "--json"])
    assert result.exit_code == 0
    d = json.loads(result.stdout)
    assert any(c["name"] == "API reachable" and c["ok"] for c in d["checks"])


def test_diagnostics_unreachable_exit_code(monkeypatch):
    import httpx

    def _boom(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(cli, "_api_get", _boom)
    result = runner.invoke(cli.app, ["diagnostics"])
    assert result.exit_code == 2


def test_completion_help():
    result = runner.invoke(cli.app, ["completion"])
    assert result.exit_code == 0
    assert "install-completion" in result.stdout
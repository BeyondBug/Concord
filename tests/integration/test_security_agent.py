"""Integration tests for the SecurityPolicyAgent (Phase 3)."""
from datetime import UTC, datetime

import pytest

from agents.security.agent import SecurityPolicyAgent
from core.models.agent_response import compute_confidence
from core.models.finding import Finding


def _finding(artifact: str) -> Finding:
    return Finding(
        id="SEC-1", source="test", artifact=artifact, severity="HIGH",
        title="t", description="d", raw={}, timestamp=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_agent_contract_fields():
    agent = SecurityPolicyAgent()
    assert agent.domain == "security"
    # Reliability must match the calibrated table used by arbitration:
    # confidence = severity_weight * source_reliability.
    assert abs(agent.source_reliability - 0.85) < 1e-9
    # HIGH severity * 0.85 reliability = 0.68 per the arbitration formula.
    assert compute_confidence("security", "HIGH") == 0.68


@pytest.mark.asyncio
async def test_agent_flags_vulnerable_source(tmp_path):
    (tmp_path / "vuln.py").write_text("exec(payload)\n", encoding="utf-8")
    agent = SecurityPolicyAgent()
    resp = await agent.analyze(_finding(str(tmp_path)))
    assert resp.agent == "security"
    assert resp.metadata["real_scan"] is True
    assert resp.metadata["violations"] >= 1
    # confidence is set by the orchestrator, not the agent
    assert resp.confidence_score == 0.0


@pytest.mark.asyncio
async def test_agent_clean_source_is_compliant(tmp_path):
    (tmp_path / "ok.py").write_text("y = 1 + 1\n", encoding="utf-8")
    agent = SecurityPolicyAgent()
    resp = await agent.analyze(_finding(str(tmp_path)))
    assert resp.metadata["violations"] == 0
    assert "No violations" in resp.root_cause


@pytest.mark.asyncio
async def test_agent_resolves_missing_artifact_without_crashing():
    agent = SecurityPolicyAgent()
    resp = await agent.analyze(_finding("/does/not/exist"))
    # Falls back to a repo-relative candidate and still returns a response.
    assert resp.agent == "security"
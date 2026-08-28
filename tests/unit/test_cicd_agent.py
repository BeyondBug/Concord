"""
tests/unit/test_cicd_agent.py
Unit tests for CICDAgent (Phase 2B — rj-karan).

These tests run without a live Trivy MCP server.
The agent falls back to the built-in KubernetesScanner automatically.
"""
from datetime import datetime

import pytest

from agents.cicd.agent import CICDAgent
from core.models.finding import Finding


def make_finding(artifact="repos/crms/k8s", severity="HIGH", source="github_actions"):
    return Finding(
        id="CVE-2024-12345",
        source=source,
        artifact=artifact,
        severity=severity,
        title="Vulnerable container image",
        description="Base image contains a known CVE.",
        raw={},
        timestamp=datetime.utcnow(),
        repository="BeyondBug/CRMS",
    )


@pytest.mark.asyncio
async def test_cicd_agent_returns_agent_response():
    """Agent always returns an AgentResponse (MCP or fallback)."""
    from core.models.agent_response import AgentResponse
    agent = CICDAgent()
    resp = await agent.analyze(make_finding())
    assert isinstance(resp, AgentResponse)


@pytest.mark.asyncio
async def test_cicd_agent_domain():
    assert CICDAgent().domain == "cicd"


@pytest.mark.asyncio
async def test_cicd_agent_source_reliability():
    assert CICDAgent().source_reliability == 0.88


@pytest.mark.asyncio
async def test_cicd_agent_finding_id_preserved():
    finding = make_finding()
    agent = CICDAgent()
    resp = await agent.analyze(finding)
    assert resp.finding_id == finding.id


@pytest.mark.asyncio
async def test_cicd_agent_has_root_cause_and_fix():
    agent = CICDAgent()
    resp = await agent.analyze(make_finding())
    assert resp.root_cause
    assert resp.suggested_fix


@pytest.mark.asyncio
async def test_cicd_agent_has_metadata():
    agent = CICDAgent()
    resp = await agent.analyze(make_finding())
    assert "scanner" in resp.metadata
    assert "target" in resp.metadata
    assert resp.metadata.get("real_scan") is True


@pytest.mark.asyncio
async def test_cicd_agent_image_artifact_detected():
    """image: prefix should be recognised as a container image."""
    agent = CICDAgent()
    # Will fall back to scanner because no MCP, but should not crash
    resp = await agent.analyze(make_finding(artifact="image:nginx:1.25"))
    assert resp.agent == "cicd"


@pytest.mark.asyncio
async def test_trivy_parse_empty_response():
    """_parse_trivy_response handles an empty Trivy result gracefully."""
    result = CICDAgent._parse_trivy_response({}, "nginx:latest")
    assert result["total"] == 0
    assert result["root_cause"]
    assert result["fix"]


@pytest.mark.asyncio
async def test_trivy_parse_with_vulnerabilities():
    """_parse_trivy_response correctly groups and sorts vulnerabilities."""
    raw = {
        "Results": [
            {
                "Target": "nginx:1.25",
                "Vulnerabilities": [
                    {"VulnerabilityID": "CVE-A", "Severity": "MEDIUM",
                     "Title": "Medium vuln", "PkgName": "libssl",
                     "FixedVersion": "1.2.3"},
                    {"VulnerabilityID": "CVE-B", "Severity": "CRITICAL",
                     "Title": "Critical vuln", "PkgName": "libc",
                     "FixedVersion": "2.0.0"},
                ],
            }
        ]
    }
    result = CICDAgent._parse_trivy_response(raw, "nginx:1.25")
    assert result["total"] == 2
    assert result["by_severity"]["CRITICAL"] == 1
    assert result["by_severity"]["MEDIUM"] == 1
    # CRITICAL should be first (highest weight)
    assert "CVE-B" in result["root_cause"]
    assert "libc" in result["fix"]
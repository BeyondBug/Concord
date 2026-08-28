"""
tests/unit/test_observability_agent.py
Unit tests for ObservabilityAgent (Phase 2B — rj-karan).

These tests run without a live HolmesGPT MCP server.
The agent falls back to the heuristic pattern matcher automatically.
"""
from datetime import datetime

import pytest

from agents.observability.agent import ObservabilityAgent
from core.models.finding import Finding


def make_alert(
    title="KubePodCrashLooping",
    description="Pod is crash-looping in namespace default",
    severity="HIGH",
    source="prometheus",
    artifact="alert:pod/crms-api-7d9b8c-xkpf2",
):
    return Finding(
        id="alert-001",
        source=source,
        artifact=artifact,
        severity=severity,
        title=title,
        description=description,
        raw={"labels": {"namespace": "default", "pod": "crms-api-7d9b8c-xkpf2"}},
        timestamp=datetime.utcnow(),
        repository="BeyondBug/CRMS",
    )


@pytest.mark.asyncio
async def test_observability_agent_returns_agent_response():
    from core.models.agent_response import AgentResponse
    agent = ObservabilityAgent()
    resp = await agent.analyze(make_alert())
    assert isinstance(resp, AgentResponse)


@pytest.mark.asyncio
async def test_observability_agent_domain():
    assert ObservabilityAgent().domain == "observability"


@pytest.mark.asyncio
async def test_observability_agent_source_reliability():
    assert ObservabilityAgent().source_reliability == 0.80


@pytest.mark.asyncio
async def test_observability_agent_finding_id_preserved():
    alert = make_alert()
    resp = await ObservabilityAgent().analyze(alert)
    assert resp.finding_id == alert.id


@pytest.mark.asyncio
async def test_observability_agent_has_root_cause_and_fix():
    resp = await ObservabilityAgent().analyze(make_alert())
    assert resp.root_cause
    assert resp.suggested_fix


@pytest.mark.asyncio
async def test_observability_agent_has_metadata():
    resp = await ObservabilityAgent().analyze(make_alert())
    assert "scanner" in resp.metadata
    assert resp.metadata.get("real_scan") is True


# ── Heuristic pattern tests ─────────────────────────────────────────────── #

def _heuristic(title="", description="", severity="HIGH", source="prometheus"):
    finding = make_alert(title=title, description=description,
                         severity=severity, source=source)
    return ObservabilityAgent._heuristic_analyse(finding)


def test_heuristic_crashloop():
    result = _heuristic(title="KubePodCrashLooping", description="restart count 15")
    assert "CrashLoopBackOff" in result["root_cause"]
    assert "kubectl logs" in result["suggested_fix"]


def test_heuristic_oom():
    result = _heuristic(title="OOMKilled", description="memory limit exceeded")
    assert "OOMKilled" in result["root_cause"] or "memory" in result["root_cause"].lower()
    assert "memory" in result["suggested_fix"].lower()


def test_heuristic_image_pull():
    result = _heuristic(title="ImagePullBackOff", description="pull access denied")
    assert "pull" in result["root_cause"].lower() or "image" in result["root_cause"].lower()
    assert "imagePullSecrets" in result["suggested_fix"] or "registry" in result["suggested_fix"]


def test_heuristic_latency():
    result = _heuristic(title="HighLatency", description="p99 latency 4500ms above threshold")
    assert "latency" in result["root_cause"].lower()


def test_heuristic_disk():
    result = _heuristic(title="DiskPressure", description="PersistentVolumeClaim near capacity")
    assert "storage" in result["root_cause"].lower() or "disk" in result["root_cause"].lower()


def test_heuristic_cert():
    result = _heuristic(title="CertificateExpiringSoon",
                        description="TLS certificate expires in 3 days")
    assert "cert" in result["root_cause"].lower() or "TLS" in result["root_cause"]


def test_heuristic_error_rate():
    result = _heuristic(title="HighErrorRate", description="HTTP 500 error rate 12%")
    assert "error" in result["root_cause"].lower()


def test_heuristic_generic_fallback():
    """Unknown alert type should return a generic response, not crash."""
    result = _heuristic(title="SomeWeirdAlert", description="nothing matches this")
    assert result["root_cause"]
    assert result["suggested_fix"]
    assert result["pattern"] == "generic"


def test_extract_labels_from_raw():
    """Labels embedded in Finding.raw are forwarded to the MCP call."""
    finding = make_alert()
    labels = ObservabilityAgent._extract_labels(finding)
    assert labels["namespace"] == "default"
    assert labels["pod"] == "crms-api-7d9b8c-xkpf2"
    assert labels["severity"] == "high"


def test_parse_holmesgpt_response_full():
    """_parse_holmesgpt_response builds root_cause with evidence."""
    raw = {
        "root_cause": "OOM kill due to memory leak in crms-api",
        "suggested_fix": "Increase memory limit to 512Mi",
        "evidence": [
            {"type": "log",    "content": "OOMKilled at 14:32 UTC"},
            {"type": "metric", "content": "memory_working_set: 480Mi"},
        ],
        "runbooks": ["https://wiki.example.com/oom"],
    }
    finding = make_alert()
    result = ObservabilityAgent._parse_holmesgpt_response(raw, finding)
    assert "OOM kill" in result["root_cause"]
    assert "Evidence" in result["root_cause"]   # evidence appended
    assert result["runbooks"] == ["https://wiki.example.com/oom"]


def test_parse_holmesgpt_response_empty():
    """Empty MCP response produces a sensible default, not an exception."""
    finding = make_alert()
    result = ObservabilityAgent._parse_holmesgpt_response({}, finding)
    assert result["root_cause"]
    assert result["suggested_fix"]
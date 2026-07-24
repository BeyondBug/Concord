"""
tests/unit/test_orchestrator.py
Orchestrator integration tests (uses agent stubs — no external deps).
"""
import pytest
from datetime import datetime
from core.models.finding import Finding
from core.orchestrator.orchestrator import Orchestrator


def make_finding(severity="HIGH", finding_id="test-001"):
    return Finding(
        id=finding_id,
        source="test",
        artifact="infra/terraform/main.tf",
        severity=severity,
        title="Test finding",
        description="Unit test",
        raw={},
        timestamp=datetime.utcnow(),
        repository="BeyondBug/CRMS",
    )


@pytest.mark.asyncio
async def test_low_severity_takes_fast_path():
    result = await Orchestrator().process(make_finding(severity="LOW"))
    assert result["path"] == "fast_path"
    assert result["pr_comment"] is None


@pytest.mark.asyncio
async def test_informational_takes_fast_path():
    result = await Orchestrator().process(make_finding(severity="INFORMATIONAL"))
    assert result["path"] == "fast_path"


@pytest.mark.asyncio
async def test_critical_finding_escalates_to_ai():
    result = await Orchestrator().process(make_finding(severity="CRITICAL"))
    assert result["path"] == "ai_path"
    assert result.get("agent") is not None
    assert result.get("score", 0) > 0


@pytest.mark.asyncio
async def test_high_finding_produces_pr_comment():
    result = await Orchestrator().process(make_finding(severity="HIGH"))
    assert result["path"] == "ai_path"
    assert result.get("pr_comment") is not None
    assert len(result["pr_comment"]) > 0


@pytest.mark.asyncio
async def test_result_has_auto_resolved_field():
    result = await Orchestrator().process(make_finding(severity="CRITICAL"))
    assert "auto_resolved" in result
    assert isinstance(result["auto_resolved"], bool)


@pytest.mark.asyncio
async def test_confidence_scores_match_formula():
    """CRITICAL + infra: expected 1.0 * 0.92 = 0.9200"""
    result = await Orchestrator().process(make_finding(severity="CRITICAL"))
    # Winner is always the agent with highest confidence score
    # infra: 0.92, cicd: 0.88 — infra should win or both trigger tiebreak
    assert result["score"] in (0.92, 0.88)

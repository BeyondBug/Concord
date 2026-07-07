"""Tests for confidence arbitration."""
from core.arbitration.resolver import arbitrate
from core.models.agent_response import AgentResponse


def resp(agent: str, score: float) -> AgentResponse:
    return AgentResponse(
        agent=agent, finding_id="f1",
        confidence_score=score,
        root_cause="test", suggested_fix="test",
    )


def test_single_response_auto_resolves():
    winner, auto = arbitrate([resp("infra", 0.736)])
    assert auto and winner.agent == "infra"


def test_clear_gap_auto_resolves():
    winner, auto = arbitrate([resp("infra", 0.92), resp("cicd", 0.44)])
    assert auto and winner.agent == "infra"


def test_close_scores_escalate():
    _, auto = arbitrate([resp("infra", 0.70), resp("cicd", 0.68)])
    assert not auto


def test_highest_score_wins():
    winner, _ = arbitrate([resp("cicd", 0.80), resp("infra", 0.92)])
    assert winner.agent == "infra"

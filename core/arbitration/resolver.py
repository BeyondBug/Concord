"""Arbitration resolver — auto-resolve vs human tiebreak."""
from core.models.agent_response import AgentResponse

CONFIDENCE_GAP_THRESHOLD = 0.15  # below this gap → escalate to human


def arbitrate(responses: list[AgentResponse]) -> tuple[AgentResponse, bool]:
    """Return (winner, auto_resolved).

    auto_resolved=True  → post fix suggestion automatically.
    auto_resolved=False → post human tiebreak request to PR.
    """
    if not responses:
        raise ValueError("no agent responses to arbitrate")
    if len(responses) == 1:
        return responses[0], True

    ranked = sorted(responses, key=lambda r: r.confidence_score, reverse=True)
    top, second = ranked[0], ranked[1]
    gap = top.confidence_score - second.confidence_score

    if gap >= CONFIDENCE_GAP_THRESHOLD:
        return top, True   # clear winner
    return top, False      # too close — human decides

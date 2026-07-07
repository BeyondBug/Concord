"""Tests for confidence scoring formula."""
from core.models.agent_response import compute_confidence


def test_critical_infra():
    assert compute_confidence("infra", "CRITICAL") == round(1.0 * 0.92, 4)


def test_low_severity_reduces_score():
    assert compute_confidence("infra", "LOW") < compute_confidence("infra", "HIGH")


def test_unknown_agent_uses_default():
    score = compute_confidence("unknown", "HIGH")
    assert 0 < score < 1

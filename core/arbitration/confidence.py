"""Confidence scoring — the core arbitration formula.

NOT self-reported LLM confidence.
Computed from empirical calibration. See design/arbitration-design.md.
"""
from core.models.agent_response import SEVERITY_WEIGHT, SOURCE_RELIABILITY


def compute_confidence(agent_domain: str, severity: str) -> float:
    sev = SEVERITY_WEIGHT.get(severity, 0.5)
    rel = SOURCE_RELIABILITY.get(agent_domain, 0.7)
    return round(sev * rel, 4)

"""AgentResponse — structured output returned by every domain agent."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResponse:
    agent: str                    # domain: infra | cicd | kubernetes | observability
    finding_id: str
    confidence_score: float       # severity_weight * source_reliability — NOT LLM self-report
    root_cause: str
    suggested_fix: str
    metadata: dict[str, Any] = field(default_factory=dict)


# Severity weights — calibrated, not LLM-generated
SEVERITY_WEIGHT: dict[str, float] = {
    "CRITICAL": 1.0,
    "HIGH":     0.8,
    "MEDIUM":   0.5,
    "LOW":      0.2,
}

# Source reliability per agent — empirical, updated as false positive rates are measured
# Do NOT change without a team discussion and a supporting test.
SOURCE_RELIABILITY: dict[str, float] = {
    "infra":         0.92,  # TerraSecure: 92.45% ML accuracy
    "cicd":          0.88,  # Trivy + Checkov combined
    "kubernetes":    0.82,  # kagent (conservative)
    "observability": 0.80,  # HolmesGPT
    "security":      0.85,  # OPA / Semgrep
}


def compute_confidence(agent_domain: str, severity: str) -> float:
    """Compute confidence score.

    This is NOT self-reported LLM confidence.
    It is deterministic: severity_weight * source_reliability.
    See design/arbitration-design.md for full rationale.
    """
    sev = SEVERITY_WEIGHT.get(severity, 0.5)
    rel = SOURCE_RELIABILITY.get(agent_domain, 0.7)
    return round(sev * rel, 4)

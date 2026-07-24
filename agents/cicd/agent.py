"""
agents/cicd/agent.py
CICDAgent — Phase 0 stub. Phase 2B (rj-karan): replace with Trivy/Checkov MCP.
"""
from agents.base import BaseAgent
from core.models.finding import Finding
from core.models.agent_response import AgentResponse

_STUBS: dict[str, tuple[str, str]] = {
    "CRITICAL": (
        "Base image python:3.11-slim contains CVE-2024-12345 (OpenSSL RCE). "
        "All containers built from this image are vulnerable to remote code execution.",
        "Update the Dockerfile base image:\n"
        "  FROM python:3.11.9-slim-bookworm\n"
        "Rebuild and push all affected container images.",
    ),
    "HIGH": (
        "Dependency requests==2.28.0 has CVE-2023-32681. "
        "HTTP redirect following can leak credentials to a third-party host.",
        "Upgrade in requirements/base.txt:\n"
        "  requests>=2.31.0",
    ),
    "MEDIUM": (
        "GitHub Actions workflow uses an unpinned action tag (e.g. @v3). "
        "Supply chain compromise possible if the tag is moved.",
        "Pin to a specific commit SHA:\n"
        "  uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
    ),
    "LOW": (
        "Docker image exceeds 500 MB. Large images increase pull latency and attack surface.",
        "Use multi-stage builds to reduce final image size.",
    ),
}
_DEFAULT = (
    "CI/CD security issue detected by Trivy/Checkov.",
    "Review pipeline configuration and apply security best practices.",
)


class CICDAgent(BaseAgent):
    """CI/CD agent backed by Trivy and Checkov.

    Phase 0: realistic stub responses by severity.
    Phase 2B (rj-karan): replace with Trivy/Checkov MCP calls + SARIF parsing.
    """

    @property
    def domain(self) -> str:
        return "cicd"

    @property
    def source_reliability(self) -> float:
        return 0.88  # Trivy + Checkov combined calibration

    async def analyze(self, finding: Finding) -> AgentResponse:
        root_cause, fix = _STUBS.get(finding.severity, _DEFAULT)
        return AgentResponse(
            agent=self.domain,
            finding_id=finding.id,
            confidence_score=0.0,   # always overwritten by orchestrator
            root_cause=root_cause,
            suggested_fix=fix,
            metadata={"scanner": "Trivy/Checkov", "phase": "0-stub"},
        )

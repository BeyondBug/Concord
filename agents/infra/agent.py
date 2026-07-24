"""
agents/infra/agent.py
InfraAgent — Phase 0 stub. Phase 2A (Jash): replace with TerraSecure MCP call.
"""
from agents.base import BaseAgent
from core.models.finding import Finding
from core.models.agent_response import AgentResponse

_STUBS: dict[str, tuple[str, str]] = {
    "CRITICAL": (
        "IAM policy grants wildcard (*) actions on wildcard (*) resources. "
        "Any principal with this policy has unrestricted account access.",
        "Restrict to minimum required actions and specific resource ARNs:\n"
        "  actions   = [\"s3:GetObject\", \"s3:PutObject\"]\n"
        "  resources = [\"arn:aws:s3:::my-bucket/*\"]",
    ),
    "HIGH": (
        "Security group allows unrestricted inbound SSH (port 22) from 0.0.0.0/0. "
        "Instance is exposed to the public internet.",
        "Restrict SSH to a known CIDR block:\n"
        "  cidr_blocks = [\"10.0.0.0/8\"]  # internal network only",
    ),
    "MEDIUM": (
        "S3 bucket has versioning disabled. "
        "Accidental deletion or overwrite cannot be recovered.",
        "Enable versioning:\n  versioning { enabled = true }",
    ),
    "LOW": (
        "Terraform resource is missing a Name tag. "
        "Cost attribution and console visibility are reduced.",
        "Add a Name tag:\n  tags = { Name = \"my-resource\" }",
    ),
}
_DEFAULT = (
    "IaC misconfiguration detected.",
    "Apply least-privilege Terraform configuration.",
)


class InfraAgent(BaseAgent):
    """Infrastructure / Terraform agent.

    Phase 0: realistic stub responses by severity.
    Phase 2A (Jash): replace with TerraSecure MCP call + SARIF parsing.
    """

    @property
    def domain(self) -> str:
        return "infra"

    @property
    def source_reliability(self) -> float:
        return 0.92  # TerraSecure ML accuracy: 92.45%

    async def analyze(self, finding: Finding) -> AgentResponse:
        root_cause, fix = _STUBS.get(finding.severity, _DEFAULT)
        return AgentResponse(
            agent=self.domain,
            finding_id=finding.id,
            confidence_score=0.0,   # always overwritten by orchestrator
            root_cause=root_cause,
            suggested_fix=fix,
            metadata={"scanner": "TerraSecure", "phase": "0-stub"},
        )

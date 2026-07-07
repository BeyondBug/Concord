"""CICDAgent — backed by Trivy + Checkov."""
from agents.base import BaseAgent
from core.models.finding import Finding
from core.models.agent_response import AgentResponse


class CICDAgent(BaseAgent):

    @property
    def domain(self) -> str:
        return "cicd"

    @property
    def source_reliability(self) -> float:
        return 0.88

    async def analyze(self, finding: Finding) -> AgentResponse:
        # TODO Phase 2B (rj-karan): call Trivy/Checkov MCP connector, parse SARIF
        raise NotImplementedError("CICDAgent.analyze() — Phase 2B (rj-karan)")

"""InfraAgent — backed by TerraSecure ML IaC scanner."""
from agents.base import BaseAgent
from core.models.finding import Finding
from core.models.agent_response import AgentResponse, compute_confidence


class InfraAgent(BaseAgent):

    @property
    def domain(self) -> str:
        return "infra"

    @property
    def source_reliability(self) -> float:
        return 0.92  # TerraSecure ML accuracy on test set

    async def analyze(self, finding: Finding) -> AgentResponse:
        # TODO Phase 2A (Jash)
        # 1. Get TerraSecure connector from registry
        # 2. POST finding.artifact to /scan endpoint
        # 3. Parse SARIF result
        # 4. Return AgentResponse with compute_confidence()
        raise NotImplementedError("InfraAgent.analyze() — Phase 2A (Jash)")

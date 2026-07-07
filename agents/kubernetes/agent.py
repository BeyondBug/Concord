"""KubernetesAgent — composed on kagent (Apache 2.0)."""
from agents.base import BaseAgent
from core.models.finding import Finding
from core.models.agent_response import AgentResponse


class KubernetesAgent(BaseAgent):

    @property
    def domain(self) -> str:
        return "kubernetes"

    @property
    def source_reliability(self) -> float:
        return 0.82

    async def analyze(self, finding: Finding) -> AgentResponse:
        # TODO Phase 2A (Jash): call kagent MCP server
        raise NotImplementedError("KubernetesAgent.analyze() — Phase 2A (Jash)")

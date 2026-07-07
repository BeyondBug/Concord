"""ObservabilityAgent — composed on HolmesGPT (MIT)."""
from agents.base import BaseAgent
from core.models.finding import Finding
from core.models.agent_response import AgentResponse


class ObservabilityAgent(BaseAgent):

    @property
    def domain(self) -> str:
        return "observability"

    @property
    def source_reliability(self) -> float:
        return 0.80

    async def analyze(self, finding: Finding) -> AgentResponse:
        # TODO Phase 2B (rj-karan): integrate HolmesGPT MCP client
        raise NotImplementedError("ObservabilityAgent.analyze() — Phase 2B (rj-karan)")

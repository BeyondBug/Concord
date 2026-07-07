"""SecurityPolicyAgent — OPA or Semgrep backed."""
from agents.base import BaseAgent
from core.models.finding import Finding
from core.models.agent_response import AgentResponse


class SecurityPolicyAgent(BaseAgent):

    @property
    def domain(self) -> str:
        return "security"

    @property
    def source_reliability(self) -> float:
        return 0.85

    async def analyze(self, finding: Finding) -> AgentResponse:
        # TODO Phase 3 (Both): implement OPA or Semgrep policy check
        raise NotImplementedError("SecurityPolicyAgent — Phase 3")

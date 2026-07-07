"""BaseAgent — every domain agent must implement this interface."""
from abc import ABC, abstractmethod
from core.models.finding import Finding
from core.models.agent_response import AgentResponse


class BaseAgent(ABC):

    @property
    @abstractmethod
    def domain(self) -> str:
        """Agent domain: infra | cicd | kubernetes | observability | security"""
        ...

    @property
    @abstractmethod
    def source_reliability(self) -> float:
        """Empirical reliability 0-1 for the backing tool.
        Used in: confidence = severity_weight * source_reliability
        """
        ...

    @abstractmethod
    async def analyze(self, finding: Finding) -> AgentResponse:
        """Analyze a finding. Call the backing tool. Return AgentResponse.

        confidence_score MUST be set using compute_confidence().
        Never use LLM self-reported confidence.
        """
        ...

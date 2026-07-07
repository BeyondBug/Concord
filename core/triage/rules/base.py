from abc import ABC, abstractmethod
from core.models.finding import Finding


class BaseRule(ABC):
    @abstractmethod
    def match(self, finding: Finding) -> tuple[bool, str]:
        """Return (matched, reason).

        matched=True  → fast path (AI not needed).
        matched=False → continue to next rule.
        """
        ...

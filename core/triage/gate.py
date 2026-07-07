"""Triage Gate — decides if AI is needed for a finding."""
from core.models.finding import Finding
from core.triage.rules.base import BaseRule


class TriageGate:
    def __init__(self, rules: list[BaseRule] | None = None):
        self.rules = rules or []

    def evaluate(self, finding: Finding) -> tuple[bool, str]:
        """Return (needs_ai, reason).

        False = fast path (no LLM call, low cost, still logged).
        True  = escalate to AI orchestrator.
        """
        for rule in self.rules:
            matched, reason = rule.match(finding)
            if matched:
                return False, reason
        return True, "no rule matched — escalating to AI"

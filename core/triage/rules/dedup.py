"""Rule: duplicate findings (seen recently) skip AI."""
from .base import BaseRule
from core.models.finding import Finding


class DedupRule(BaseRule):
    def match(self, finding: Finding) -> tuple[bool, str]:
        # TODO Phase 1: Redis-backed fingerprint store
        return False, ""

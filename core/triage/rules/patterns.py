"""Rule: known finding fingerprints never need re-analysis."""
from core.models.finding import Finding

from .base import BaseRule


class KnownPatternRule(BaseRule):
    def __init__(self, known_ids: set[str]):
        self.known_ids = known_ids

    def match(self, finding: Finding) -> tuple[bool, str]:
        if finding.id in self.known_ids:
            return True, "known pattern — no AI needed"
        return False, ""

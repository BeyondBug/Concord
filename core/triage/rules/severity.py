"""Rule: low-severity findings skip AI."""
from core.models.finding import Finding

from .base import BaseRule

FAST_PATH_SEVERITIES = {"LOW", "INFORMATIONAL"}


class LowSeverityRule(BaseRule):
    def match(self, finding: Finding) -> tuple[bool, str]:
        if finding.severity in FAST_PATH_SEVERITIES:
            return True, f"severity={finding.severity} below AI threshold"
        return False, ""

"""Rule: low-severity findings skip AI."""
from .base import BaseRule
from core.models.finding import Finding

FAST_PATH_SEVERITIES = {"LOW", "INFORMATIONAL"}


class LowSeverityRule(BaseRule):
    def match(self, finding: Finding) -> tuple[bool, str]:
        if finding.severity in FAST_PATH_SEVERITIES:
            return True, f"severity={finding.severity} below AI threshold"
        return False, ""

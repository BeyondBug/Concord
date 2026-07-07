"""Tests for the triage gate rule engine."""
from datetime import datetime
from core.triage.gate import TriageGate
from core.triage.rules.severity import LowSeverityRule
from core.triage.rules.patterns import KnownPatternRule
from core.models.finding import Finding


def make_finding(severity: str = "HIGH", finding_id: str = "f1") -> Finding:
    return Finding(
        id=finding_id, source="test", artifact="main.tf",
        severity=severity, title="Test", description="",
        raw={}, timestamp=datetime.utcnow(),
    )


def test_low_severity_fast_path():
    gate = TriageGate(rules=[LowSeverityRule()])
    needs_ai, reason = gate.evaluate(make_finding(severity="LOW"))
    assert not needs_ai
    assert "LOW" in reason


def test_high_severity_escalates():
    gate = TriageGate(rules=[LowSeverityRule()])
    needs_ai, _ = gate.evaluate(make_finding(severity="HIGH"))
    assert needs_ai


def test_known_pattern_fast_path():
    gate = TriageGate(rules=[KnownPatternRule(known_ids={"CVE-2024-33663"})])
    needs_ai, _ = gate.evaluate(make_finding(finding_id="CVE-2024-33663"))
    assert not needs_ai


def test_empty_rules_always_escalates():
    gate = TriageGate(rules=[])
    needs_ai, _ = gate.evaluate(make_finding(severity="CRITICAL"))
    assert needs_ai

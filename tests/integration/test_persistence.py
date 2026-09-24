"""Tests for core.persistence and its integration with the orchestrator.

Every test runs against an in-memory SQLite store so nothing touches disk and
the state is isolated per test.
"""
from datetime import UTC, datetime

import pytest

from core.models.finding import Finding
from core.persistence import AuditRecord, FindingRecord, SQLiteStore
from core.persistence import store as store_mod


@pytest.fixture
def mem_store():
    s = SQLiteStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def orchestrator_with_mem_store():
    """Point the orchestrator's global store at a fresh in-memory DB."""
    s = store_mod._reset_store_for_tests(":memory:")
    yield s
    s.clear()


def test_add_and_get_finding(mem_store):
    mem_store.add_finding(FindingRecord(
        id="F-1", severity="HIGH", artifact="a.tf", repo="r", source="s",
        path="ai_path", agent="infra", result={"path": "ai_path", "agent": "infra"},
    ))
    got = mem_store.get_finding("F-1")
    assert got is not None
    assert got["agent"] == "infra"
    assert got["result"]["path"] == "ai_path"


def test_list_findings_orders_newest_first(mem_store):
    for i in range(3):
        mem_store.add_finding(FindingRecord(
            id=f"F-{i}", severity="LOW", artifact="x", repo="", source="",
            path="fast_path", agent=None, result={"path": "fast_path"},
        ))
    rows = mem_store.list_findings()
    assert [r["id"] for r in rows] == ["F-2", "F-1", "F-0"]


def test_finding_stats_counts_paths_and_tiebreaks(mem_store):
    mem_store.add_finding(FindingRecord(
        id="A", severity="LOW", artifact="x", repo="", source="",
        path="fast_path", agent=None, result={"path": "fast_path"}))
    mem_store.add_finding(FindingRecord(
        id="B", severity="HIGH", artifact="x", repo="", source="",
        path="ai_path", agent="infra",
        result={"path": "ai_path", "auto_resolved": False}))
    stats = mem_store.finding_stats()
    assert stats == {"total": 2, "fast": 1, "ai": 1, "tiebreaks": 1}


def test_audit_records_persist(mem_store):
    mem_store.add_audit(AuditRecord(
        finding_id="F-1", path="fast_path", reason="low sev", agent=None))
    entries = mem_store.list_audit()
    assert len(entries) == 1
    assert entries[0]["finding_id"] == "F-1"


def test_list_limit_is_bounded(mem_store):
    for i in range(5):
        mem_store.add_finding(FindingRecord(
            id=f"F-{i}", severity="LOW", artifact="x", repo="", source="",
            path="fast_path", agent=None, result={}))
    assert len(mem_store.list_findings(limit=2)) == 2
    # limit is clamped to >= 1
    assert len(mem_store.list_findings(limit=0)) == 1


@pytest.mark.asyncio
async def test_orchestrator_persists_fast_path(orchestrator_with_mem_store):
    from core.orchestrator.orchestrator import Orchestrator

    finding = Finding(
        id="LOW-1", source="t", artifact="x", severity="LOW",
        title="t", description="d", raw={}, timestamp=datetime.now(UTC))
    result = await Orchestrator().process(finding)
    assert result["path"] == "fast_path"

    s = orchestrator_with_mem_store
    assert s.get_finding("LOW-1") is not None            # finding persisted
    audit = s.list_audit()
    assert any(a["finding_id"] == "LOW-1" and a["path"] == "fast_path"
               for a in audit)                            # audit persisted


@pytest.mark.asyncio
async def test_orchestrator_audits_every_finding(orchestrator_with_mem_store):
    """The 'every finding is audited, including fast-path' invariant."""
    from core.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator()
    for fid, sev in [("L1", "LOW"), ("L2", "INFORMATIONAL")]:
        await orch.process(Finding(
            id=fid, source="t", artifact="x", severity=sev,
            title="t", description="d", raw={}, timestamp=datetime.now(UTC)))

    audited_ids = {a["finding_id"] for a in orchestrator_with_mem_store.list_audit()}
    assert {"L1", "L2"} <= audited_ids

def test_severity_breakdown(mem_store):
    for sev in ["HIGH", "HIGH", "LOW", "CRITICAL"]:
        mem_store.add_finding(FindingRecord(
            id=f"S-{sev}-{id(object())}", severity=sev, artifact="x",
            repo="", source="", path="fast_path", agent=None, result={}))
    bd = mem_store.severity_breakdown()
    assert bd.get("HIGH") == 2
    assert bd.get("LOW") == 1
    assert bd.get("CRITICAL") == 1
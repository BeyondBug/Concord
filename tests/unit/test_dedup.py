"""Tests for the dedup fingerprint store and DedupRule."""
from datetime import UTC, datetime

from core.models.finding import Finding
from core.triage.rules.dedup import DedupRule
from core.triage.rules.dedup_store import (
    InMemoryDedupStore,
    fingerprint,
    get_dedup_store,
)


def _finding(fid="F-1", severity="HIGH", artifact="a.tf"):
    return Finding(
        id=fid, source="scanner", artifact=artifact, severity=severity,
        title="t", description="d", raw={}, timestamp=datetime.now(UTC),
    )


# ── fingerprint ────────────────────────────────────────────────────────

def test_fingerprint_ignores_timestamp():
    f1 = _finding()
    f2 = _finding()  # different timestamp instance, same identity
    assert fingerprint(f1) == fingerprint(f2)


def test_fingerprint_changes_with_identity():
    assert fingerprint(_finding(fid="A")) != fingerprint(_finding(fid="B"))
    assert fingerprint(_finding(severity="HIGH")) != fingerprint(
        _finding(severity="LOW"))


# ── in-memory store ─────────────────────────────────────────────────────

def test_in_memory_first_unseen_then_seen():
    store = InMemoryDedupStore()
    fp = "abc"
    assert store.seen_before(fp) is False   # first time: unseen
    assert store.seen_before(fp) is True    # second time: duplicate


def test_in_memory_ttl_expiry(monkeypatch):
    store = InMemoryDedupStore(ttl_seconds=0)  # everything expires immediately
    assert store.seen_before("x") is False
    # ttl=0 means the recorded entry is already expired on the next check
    assert store.seen_before("x") is False


def test_get_dedup_store_falls_back_without_redis(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    store = get_dedup_store()
    assert isinstance(store, InMemoryDedupStore)


def test_get_dedup_store_falls_back_on_bad_redis(monkeypatch):
    # Unreachable Redis → graceful in-memory fallback, no exception.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1")  # nothing listening
    store = get_dedup_store()
    assert isinstance(store, InMemoryDedupStore)


# ── DedupRule ────────────────────────────────────────────────────────────

def test_rule_first_call_no_match():
    rule = DedupRule(store=InMemoryDedupStore())
    matched, reason = rule.match(_finding())
    assert matched is False


def test_rule_second_call_matches():
    rule = DedupRule(store=InMemoryDedupStore())
    f = _finding()
    rule.match(f)
    matched, reason = rule.match(f)
    assert matched is True
    assert "duplicate" in reason.lower()


def test_rule_distinct_findings_do_not_dedup():
    rule = DedupRule(store=InMemoryDedupStore())
    assert rule.match(_finding(fid="A"))[0] is False
    assert rule.match(_finding(fid="B"))[0] is False


def test_rule_lazy_store_default(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    rule = DedupRule()  # no store injected; resolves default lazily
    assert rule.match(_finding(fid="LAZY"))[0] is False
    assert isinstance(rule.store, InMemoryDedupStore)


# ── RedisDedupStore against a fake client (no server needed) ─────────────

class _FakeRedis:
    def __init__(self):
        self.data = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None  # not created → already seen
        self.data[key] = value
        return True


def test_redis_store_semantics():
    from core.triage.rules.dedup_store import RedisDedupStore
    store = RedisDedupStore(_FakeRedis())
    assert store.seen_before("fp1") is False  # created → unseen
    assert store.seen_before("fp1") is True   # NX blocks → seen
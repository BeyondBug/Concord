"""
Rule: duplicate findings seen within a TTL window skip AI (fast path).

Backed by a fingerprint store (Redis when REDIS_URL is reachable, otherwise an
in-process TTL cache — see dedup_store.py). The rule stays a no-arg constructor
so existing wiring (Orchestrator builds DedupRule()) keeps working; inject a
custom store in tests.
"""
from core.models.finding import Finding
from core.triage.rules.base import BaseRule
from core.triage.rules.dedup_store import fingerprint, get_dedup_store


class DedupRule(BaseRule):
    def __init__(self, store=None):
        # Lazily resolve the default store so importing the rule never needs
        # a live Redis connection.
        self._store = store

    @property
    def store(self):
        if self._store is None:
            self._store = get_dedup_store()
        return self._store

    def match(self, finding: Finding) -> tuple[bool, str]:
        fp = fingerprint(finding)
        if self.store.seen_before(fp):
            return True, "duplicate finding seen recently — no AI needed"
        return False, ""
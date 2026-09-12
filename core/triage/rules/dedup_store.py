"""
core/triage/rules/dedup_store.py
Fingerprint stores for the dedup triage rule.

A finding "fingerprint" identifies a finding by its stable identity (id, source,
artifact, severity) — deliberately excluding volatile fields like timestamp — so
the same issue seen again within a TTL window can skip re-analysis (fast path).

Two backends behind one tiny interface:
  - RedisDedupStore   : shared across processes; used when REDIS_URL is set and
                        reachable. Uses SET key with an expiry (SETEX semantics).
  - InMemoryDedupStore: per-process TTL cache; the graceful fallback when Redis
                        is unavailable so triage never crashes on a missing
                        service (fail-safe).

``get_dedup_store()`` picks Redis when it can connect, otherwise falls back to
in-memory and logs the downgrade once.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time

logger = logging.getLogger("concord.dedup")

DEFAULT_TTL_SECONDS = 3600
_KEY_PREFIX = "concord:dedup:"


def fingerprint(finding) -> str:
    """Stable content hash of a finding's identity (excludes timestamp)."""
    basis = "|".join([
        getattr(finding, "id", "") or "",
        getattr(finding, "source", "") or "",
        getattr(finding, "artifact", "") or "",
        getattr(finding, "severity", "") or "",
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


class InMemoryDedupStore:
    """Per-process TTL cache. Not shared across workers, but never fails."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.ttl = ttl_seconds
        self._seen: dict[str, float] = {}

    def seen_before(self, fp: str) -> bool:
        """Return True if fp was recorded within the TTL; record it either way."""
        now = time.monotonic()
        self._evict(now)
        if fp in self._seen:
            return True
        self._seen[fp] = now + self.ttl
        return False

    def _evict(self, now: float) -> None:
        expired = [k for k, exp in self._seen.items() if exp <= now]
        for k in expired:
            del self._seen[k]


class RedisDedupStore:
    """Shared dedup store backed by Redis with per-key expiry."""

    def __init__(self, client, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._r = client
        self.ttl = ttl_seconds

    def seen_before(self, fp: str) -> bool:
        key = _KEY_PREFIX + fp
        # SET key value NX EX ttl -> returns True only if the key was created,
        # i.e. it was NOT seen before. Atomic; no read-then-write race.
        created = self._r.set(key, "1", nx=True, ex=self.ttl)
        return not created


def get_dedup_store(ttl_seconds: int = DEFAULT_TTL_SECONDS):
    """Return a Redis-backed store if reachable, else in-memory fallback."""
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return InMemoryDedupStore(ttl_seconds)
    try:
        import redis  # imported lazily so the dep is optional at runtime
        client = redis.Redis.from_url(url, socket_connect_timeout=1,
                                      socket_timeout=1, decode_responses=True)
        client.ping()
        logger.info("Dedup using Redis")
        return RedisDedupStore(client, ttl_seconds)
    except Exception as exc:  # noqa: BLE001 - any Redis failure → safe fallback
        logger.warning("Redis unavailable (%s); dedup falling back to in-memory.",
                       exc)
        return InMemoryDedupStore(ttl_seconds)
"""
agents/base/remote.py
Shared plumbing for agents backed by an external service (kagent, HolmesGPT).

An external agent is only ever reported "active" after a live probe of its
connector succeeds. Anything else — no connector in the manifest, a missing
token, plaintext URL without the opt-in, a refused connection, a failing health
check — yields "blocked" with the concrete reason, so the UI, CLI and
orchestrator all tell the same, honest story.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

from core.credential_broker import CredentialBroker
from core.manifest import load_manifest
from core.mcp_runtime.registry import ToolRegistry
from core.mcp_runtime.transport import SecureTransport
from core.models.manifest import ConnectorConfig

logger = logging.getLogger("concord.agent.remote")

DEFAULT_MANIFEST = "connectors/tools.yaml"
PROBE_TIMEOUT_SECONDS = 4.0
_STATUS_TTL_SECONDS = 15.0


@dataclass
class BackendStatus:
    state: str              # "active" | "blocked"
    detail: str             # human-readable reason / what was verified
    connector: str | None = None
    url: str | None = None
    checked_at: float = field(default_factory=time.time)   # epoch seconds

    @property
    def active(self) -> bool:
        return self.state == "active"


def manifest_path() -> str:
    return os.getenv("CONCORD_MANIFEST", DEFAULT_MANIFEST)


def connector_for(domain: str) -> tuple[ConnectorConfig | None, str]:
    """Return (connector, reason). reason explains a None connector."""
    path = manifest_path()
    try:
        registry = ToolRegistry(load_manifest(path))
    except FileNotFoundError:
        return None, f"manifest not found: {path}"
    except Exception as exc:  # noqa: BLE001 - invalid manifest must not crash callers
        return None, f"manifest invalid ({path}): {exc}"
    connectors = registry.get_connectors_for_agent(domain)
    if not connectors:
        return None, f"no '{domain}' connector declared in {path}"
    return connectors[0], ""


def transport() -> SecureTransport:
    return SecureTransport(CredentialBroker())


class StatusCache:
    """Probe results, cached so dashboard polling cannot hammer backends.

    Stale-while-revalidate: once a result exists, callers get it immediately
    (``checked_at`` says how old it is) while an expired entry is re-probed
    in the background. Only the very first call waits for a probe. Callers
    that must act on fresh state (the orchestrator, before invoking an agent)
    pass ``fresh=True``.
    """

    def __init__(self, ttl: float = _STATUS_TTL_SECONDS):
        self.ttl = ttl
        self._value: BackendStatus | None = None
        self._at = 0.0
        self._lock = asyncio.Lock()
        self._refresh: asyncio.Task | None = None

    async def get(self, probe, fresh: bool = False) -> BackendStatus:
        if fresh or self._value is None:
            return await self._probe(probe)
        if time.monotonic() - self._at >= self.ttl and (
                self._refresh is None or self._refresh.done()):
            self._refresh = asyncio.create_task(self._probe(probe))
        return self._value

    async def _probe(self, probe) -> BackendStatus:
        async with self._lock:
            value = await probe()
            self._value, self._at = value, time.monotonic()
            return value

    def clear(self) -> None:
        self._value = None
        self._refresh = None


def blocked(detail: str, connector: ConnectorConfig | None = None) -> BackendStatus:
    return BackendStatus("blocked", detail,
                         connector.name if connector else None,
                         connector.url if connector else None)


def describe_error(exc: BaseException) -> str:
    """Short, secret-free description of a probe/call failure."""
    text = str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {text}"[:300]

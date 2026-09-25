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
from dataclasses import dataclass

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
    """Caches probe results briefly so dashboard polling cannot hammer backends."""

    def __init__(self, ttl: float = _STATUS_TTL_SECONDS):
        self.ttl = ttl
        self._value: BackendStatus | None = None
        self._at = 0.0
        self._lock = asyncio.Lock()

    async def get(self, probe) -> BackendStatus:
        async with self._lock:
            if self._value is not None and time.monotonic() - self._at < self.ttl:
                return self._value
            self._value = await probe()
            self._at = time.monotonic()
            return self._value

    def clear(self) -> None:
        self._value = None


def blocked(detail: str, connector: ConnectorConfig | None = None) -> BackendStatus:
    return BackendStatus("blocked", detail,
                         connector.name if connector else None,
                         connector.url if connector else None)


def describe_error(exc: BaseException) -> str:
    """Short, secret-free description of a probe/call failure."""
    text = str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {text}"[:300]

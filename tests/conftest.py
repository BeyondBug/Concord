"""Shared pytest fixtures.

Force all tests onto an in-memory SQLite store so the suite never writes a
concord.db file to disk and each session starts from a clean state.
"""
import os

os.environ.setdefault("CONCORD_DB_PATH", ":memory:")
# The app refuses to start without a webhook secret; tests sign with this one.
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
# Tests declare their own connectors; never reach a live kagent/HolmesGPT.
os.environ["CONCORD_MANIFEST"] = os.path.join(
    os.path.dirname(__file__), "fixtures", "manifest_local_only.yaml")

import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402

import pytest  # noqa: E402

from core.persistence import store as store_mod  # noqa: E402
from core.triage.rules import dedup_store  # noqa: E402


def _clear_agent_status_caches():
    from agents.kubernetes import agent as k8s_agent
    from agents.observability import agent as obs_agent
    k8s_agent._STATUS.clear()
    obs_agent._STATUS.clear()


@pytest.fixture(autouse=True)
def _isolate_global_store():
    """Give every test a fresh in-memory global store and dedup cache."""
    store_mod._reset_store_for_tests(":memory:")
    dedup_store.reset_shared_dedup_store()
    _clear_agent_status_caches()
    yield

def github_signature(body: bytes, secret: str | None = None) -> str:
    """X-Hub-Signature-256 value for body, as GitHub computes it."""
    key = (secret or os.environ["WEBHOOK_SECRET"]).encode()
    return "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()


@pytest.fixture
def post_github():
    """POST a signed GitHub webhook: post_github(client, payload_or_bytes, **headers)."""
    def _post(client, payload, headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        h = {"Content-Type": "application/json",
             "X-Hub-Signature-256": github_signature(body), **(headers or {})}
        return client.post("/events/github", content=body, headers=h)
    return _post

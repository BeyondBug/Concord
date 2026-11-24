"""Shared pytest fixtures.

Force all tests onto an in-memory SQLite store so the suite never writes a
concord.db file to disk and each session starts from a clean state.
"""
import os

os.environ.setdefault("CONCORD_DB_PATH", ":memory:")
# Tests declare their own connectors; never reach a live kagent/HolmesGPT.
os.environ["CONCORD_MANIFEST"] = os.path.join(
    os.path.dirname(__file__), "fixtures", "manifest_local_only.yaml")

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
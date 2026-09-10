"""Shared pytest fixtures.

Force all tests onto an in-memory SQLite store so the suite never writes a
concord.db file to disk and each session starts from a clean state.
"""
import os

os.environ.setdefault("CONCORD_DB_PATH", ":memory:")

import pytest  # noqa: E402

from core.persistence import store as store_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_global_store():
    """Give every test a fresh in-memory global store."""
    store_mod._reset_store_for_tests(":memory:")
    yield
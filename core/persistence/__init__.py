"""Persistence layer — swappable finding + audit storage.

Default backend is SQLite (stdlib, zero external services) so the platform
runs and is testable out of the box. Set CONCORD_DB_PATH to control the file,
or CONCORD_DB_PATH=":memory:" for an ephemeral store.
"""
from core.persistence.store import (
    AuditRecord,
    FindingRecord,
    SQLiteStore,
    get_store,
)

__all__ = ["FindingRecord", "AuditRecord", "SQLiteStore", "get_store"]
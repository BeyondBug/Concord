"""Audit Log — every finding decision recorded, including fast-path."""
import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("concord.audit")


@dataclass
class AuditEntry:
    finding_id: str
    path: str           # "fast_path" | "ai_path"
    reason: str
    agent: str | None   # None for fast-path
    timestamp: datetime


class AuditLog:
    def record(self, entry: AuditEntry) -> None:
        logger.info(
            "AUDIT finding=%s path=%s reason=%s agent=%s",
            entry.finding_id, entry.path, entry.reason, entry.agent,
        )
        # TODO Phase 1: persist to PostgreSQL audit table

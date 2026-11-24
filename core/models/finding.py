"""Finding — the core data unit that flows through all of Concord."""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Finding IDs end up in URLs, logs and audit records: only these characters.
ID_PATTERN = r"^[A-Za-z0-9._:-]+$"
ID_MAX_LEN = 200


@dataclass
class Finding:
    id: str                        # unique finding ID by CVEs
    source: str                    # which scanner produced this
    artifact: str                  # what was scanned (file path, image, manifest)
    severity: str                  # CRITICAL | HIGH | MEDIUM | LOW
    title: str
    description: str
    raw: dict[str, Any]            # original scanner output (SARIF 2.1.0 or native)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    repository: str = ""           # source repo (e.g. BeyondBug/CRMS)
    pr_number: int | None = None   # PR that triggered this
    commit_sha: str = ""
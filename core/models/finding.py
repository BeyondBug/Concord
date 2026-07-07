"""Finding — the core data unit that flows through all of Concord."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Finding:
    id: str                        # unique finding ID (e.g. CVE-2024-33663)
    source: str                    # which scanner produced this
    artifact: str                  # what was scanned (file path, image, manifest)
    severity: str                  # CRITICAL | HIGH | MEDIUM | LOW
    title: str
    description: str
    raw: dict[str, Any]            # original scanner output (SARIF 2.1.0 or native)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    repository: str = ""           # source repo (e.g. BeyondBug/CRMS)
    pr_number: int | None = None   # PR that triggered this
    commit_sha: str = ""

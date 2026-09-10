"""
agents/security/agent.py
SecurityPolicyAgent — real source-code policy scan using core.scanner.

Phase 3. Dependency-free (no OPA/Semgrep binary required); the pattern set
lives in core.scanner.SourceCodeScanner. Designed so it can later be swapped
for an OPA or Semgrep MCP connector without changing this contract.

Contract
--------
purpose        : flag high-signal injection / secret-handling anti-patterns
                 in application source code (py, js, ts, go, php).
inputs         : Finding.artifact — a file or directory path. If it does not
                 resolve, a small set of repo-relative candidates is tried.
output         : AgentResponse with root_cause + suggested_fix populated from
                 the scan. confidence_score is left 0.0 here and set by the
                 orchestrator via compute_confidence() — never LLM self-report.
error behavior : filesystem errors are logged and skipped per-file; a scan
                 over a path with no source files returns a compliant result
                 rather than raising.
timeout        : the blocking scan runs in a thread executor so it never
                 blocks the event loop.
permission     : read-only filesystem access to the artifact path.
audit          : the orchestrator records the agent decision to the audit log.
"""
import asyncio
import logging
from pathlib import Path

from agents.base import BaseAgent
from core.models.agent_response import AgentResponse
from core.models.finding import Finding
from core.scanner import SourceCodeScanner, scan_to_dict

logger = logging.getLogger("concord.agent.security")

_CANDIDATES = [
    "repos/crms",
    "core",
    "agents",
    ".",
]


class SecurityPolicyAgent(BaseAgent):
    """Application-source security policy agent (Semgrep-style patterns)."""

    @property
    def domain(self) -> str:
        return "security"

    @property
    def source_reliability(self) -> float:
        # Must match SOURCE_RELIABILITY["security"] in core.models.agent_response.
        return 0.85

    async def analyze(self, finding: Finding) -> AgentResponse:
        target = self._resolve(finding.artifact)
        logger.info("[SECURITY]  scanning %s", target)

        loop = asyncio.get_event_loop()
        scanner = SourceCodeScanner()
        raw = await loop.run_in_executor(None, scanner.scan, target)
        result = scan_to_dict(raw, target)

        logger.info("[SECURITY]  %d violations found", result["total"])
        return AgentResponse(
            agent=self.domain,
            finding_id=finding.id,
            confidence_score=0.0,  # set by orchestrator via compute_confidence()
            root_cause=result["root_cause"],
            suggested_fix=result["fix"],
            metadata={
                "scanner": "concord-source-scanner",
                "target": target,
                "violations": result["total"],
                "by_severity": result.get("by_severity", {}),
                "real_scan": True,
            },
        )

    def _resolve(self, artifact: str) -> str:
        if artifact and Path(artifact).exists():
            return artifact
        for candidate in _CANDIDATES:
            if Path(candidate).exists():
                return candidate
        return "."
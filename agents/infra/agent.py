"""
agents/infra/agent.py
InfraAgent — real Terraform security scan using core.scanner.
Works on Python 3.13. No Checkov dependency.
Phase 2A (Jash): swap for TerraSecure MCP call.
"""
import asyncio
import logging
from pathlib import Path

from agents.base import BaseAgent
from core.models.agent_response import AgentResponse
from core.models.finding import Finding
from core.scanner import TerraformScanner, scan_to_dict

logger = logging.getLogger("concord.agent.infra")

_CANDIDATES = [
    "repos/crms/infra",
    "repos/crms",
    "tests/fixtures/terraform",
    "infra",
    ".",
]


class InfraAgent(BaseAgent):
    """
    Infrastructure / Terraform agent.
    Runs real pattern-based Terraform scan.
    Phase 2A (Jash): replace with TerraSecure MCP call.
    """

    @property
    def domain(self) -> str:
        return "infra"

    @property
    def source_reliability(self) -> float:
        return 0.92

    async def analyze(self, finding: Finding) -> AgentResponse:
        target = self._resolve(finding.artifact)
        logger.info("[INFRA]  scanning %s", target)

        loop    = asyncio.get_event_loop()
        scanner = TerraformScanner()
        raw     = await loop.run_in_executor(None, scanner.scan, target)
        result  = scan_to_dict(raw, target)

        logger.info("[INFRA]  %d violations found", result["total"])
        return AgentResponse(
            agent=self.domain,
            finding_id=finding.id,
            confidence_score=0.0,
            root_cause=result["root_cause"],
            suggested_fix=result["fix"],
            metadata={
                "scanner":    "concord-terraform-scanner",
                "target":     target,
                "violations": result["total"],
                "by_severity": result.get("by_severity", {}),
                "real_scan":  True,
            },
        )

    def _resolve(self, artifact: str) -> str:
        if artifact and Path(artifact).exists():
            return artifact
        for c in _CANDIDATES:
            if Path(c).exists():
                return c
        return "."

"""
agents/cicd/agent.py
CICDAgent — real Kubernetes security scan using core.scanner.
Works on Python 3.13. No Checkov dependency.
Phase 2B (rj-karan): replace with Trivy MCP call.
"""
import asyncio
import logging
from pathlib import Path

from agents.base import BaseAgent
from core.models.agent_response import AgentResponse
from core.models.finding import Finding
from core.scanner import KubernetesScanner, scan_to_dict

logger = logging.getLogger("concord.agent.cicd")

_CANDIDATES = [
    "repos/crms/k8s",
    "repos/crms",
    "k8s",
    ".",
]


class CICDAgent(BaseAgent):
    """
    CI/CD agent.
    Runs real pattern-based Kubernetes manifest scan.
    Phase 2B (rj-karan): replace with Trivy MCP call.
    """

    @property
    def domain(self) -> str:
        return "cicd"

    @property
    def source_reliability(self) -> float:
        return 0.88

    async def analyze(self, finding: Finding) -> AgentResponse:
        target = self._resolve(finding.artifact)
        logger.info("[CICD]  scanning %s", target)

        loop    = asyncio.get_event_loop()
        scanner = KubernetesScanner()
        raw     = await loop.run_in_executor(None, scanner.scan, target)
        result  = scan_to_dict(raw, target)

        logger.info("[CICD]  %d violations found", result["total"])
        return AgentResponse(
            agent=self.domain,
            finding_id=finding.id,
            confidence_score=0.0,
            root_cause=result["root_cause"],
            suggested_fix=result["fix"],
            metadata={
                "scanner":    "concord-k8s-scanner",
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

"""
agents/observability/agent.py
ObservabilityAgent — HolmesGPT MCP-backed alert investigation.
Phase 2B (rj-karan): full implementation.

Call order:
  1. HolmesGPT MCP → investigate_alert
  2. Fallback       → built-in heuristic pattern matcher (zero external deps)

MCP protocol (Concord subset):
  POST /mcp/tool  { "tool": "investigate_alert", "input": { ... } }
  →               { "result": { "root_cause": "...", "suggested_fix": "...",
                                "evidence": [...], "runbooks": [...] },
                    "error": null }

Source reliability: 0.80  (HolmesGPT calibration — agent_response.py)
"""
import logging
import os
import re

import httpx

from agents.base import BaseAgent
from core.credential_broker import CredentialBroker
from core.models.agent_response import AgentResponse, compute_confidence
from core.models.finding import Finding

logger = logging.getLogger("concord.agent.observability")

_HOLMES_MCP_URL = os.getenv("HOLMESGPT_MCP_URL", "http://localhost:8005")
_HOLMES_TIMEOUT = float(os.getenv("HOLMESGPT_TIMEOUT", "60"))

# ── Heuristic rules: (regex, root_cause, fix) ─────────────────────────────
_HEURISTIC_RULES: list[tuple[str, str, str]] = [
    (
        r"OOMKilled|out.of.memory|memory.*limit",
        "Container OOMKilled — memory limit is too low for the current workload.",
        "Increase resources.limits.memory in the Pod spec. "
        "Consider a HorizontalPodAutoscaler if load spikes are periodic.",
    ),
    (
        r"CrashLoopBackOff|crash.loop|restart.*count",
        "Container CrashLoopBackOff — repeated restarts indicate an application "
        "or configuration error.",
        "Run `kubectl logs <pod> --previous` to retrieve the last crash output. "
        "Check liveness probe config and startup command.",
    ),
    (
        r"ImagePullBackOff|ErrImagePull|pull.*image",
        "Image pull failure — registry unreachable or image tag does not exist.",
        "Verify the image tag exists in the registry. "
        "Check imagePullSecrets if pulling from a private registry.",
    ),
    (
        r"Pending|unschedul|insufficient.*cpu|insufficient.*memory",
        "Pod stuck in Pending — scheduler cannot place it due to insufficient "
        "cluster resources.",
        "Run `kubectl describe pod <pod>` to see the scheduler event. "
        "Scale the node group or reduce resource requests.",
    ),
    (
        r"latency.*high|p99|slow.*request|timeout",
        "High latency detected — p99 latency is above threshold, suggesting "
        "resource saturation or a slow downstream dependency.",
        "Profile with `kubectl top pod`. Check Prometheus metrics for CPU "
        "throttling and downstream error rates.",
    ),
    (
        r"disk.*full|PersistentVolumeClaim|storage.*pressure",
        "Storage pressure — PVC near capacity or node disk is full.",
        "Expand the PVC if the StorageClass supports volume expansion. "
        "Prune unused images on affected nodes with `docker system prune`.",
    ),
    (
        r"certificate.*expir|TLS.*expir|cert.*expir",
        "TLS certificate approaching expiry — services will reject connections.",
        "Renew the certificate. With cert-manager: "
        "`kubectl annotate cert <name> cert-manager.io/issue-temporary-cert=true`.",
    ),
    (
        r"error.rate|5xx|HTTP.*5[0-9][0-9]",
        "Elevated error rate — HTTP 5xx responses indicate application or "
        "upstream failure.",
        "Check application logs and Prometheus error-rate dashboards. "
        "Review recent deployments and roll back if correlated.",
    ),
]


class ObservabilityAgent(BaseAgent):

    @property
    def domain(self) -> str:
        return "observability"

    @property
    def source_reliability(self) -> float:
        return 0.80

    # ------------------------------------------------------------------ #

    async def analyze(self, finding: Finding) -> AgentResponse:
        logger.info(
            "[OBS]  alert=%s  severity=%s  artifact=%s",
            finding.id, finding.severity, finding.artifact,
        )

        # ── 1. HolmesGPT MCP ──────────────────────────────────────────
        try:
            token  = CredentialBroker().get_token("holmesgpt")
            result = await self._call_holmesgpt_mcp(token, finding)
            logger.info("[OBS]  HolmesGPT MCP → %s", result["root_cause"][:60])
            return AgentResponse(
                agent=self.domain,
                finding_id=finding.id,
                confidence_score=compute_confidence(self.domain, finding.severity),
                root_cause=result["root_cause"],
                suggested_fix=result["suggested_fix"],
                metadata={
                    "scanner":   "holmesgpt-mcp",
                    "evidence":  result.get("evidence", []),
                    "runbooks":  result.get("runbooks", []),
                    "mcp_url":   _HOLMES_MCP_URL,
                    "real_scan": True,
                },
            )
        except ValueError as exc:
            logger.warning("[OBS]  no HOLMESGPT_TOKEN (%s) — fallback", exc)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning("[OBS]  HolmesGPT MCP unreachable (%s) — fallback", exc)
        except Exception as exc:
            logger.error("[OBS]  HolmesGPT MCP error: %s", exc)

        # ── 2. Fallback: heuristic ─────────────────────────────────────
        logger.info("[OBS]  fallback → heuristic analyser")
        result = self._heuristic_analyse(finding)
        logger.info("[OBS]  heuristic → %s", result["root_cause"][:60])
        return AgentResponse(
            agent=self.domain,
            finding_id=finding.id,
            confidence_score=compute_confidence(self.domain, finding.severity),
            root_cause=result["root_cause"],
            suggested_fix=result["suggested_fix"],
            metadata={
                "scanner":      "concord-heuristic (fallback)",
                "pattern":      result.get("pattern", "generic"),
                "real_scan":    True,
                "mcp_fallback": True,
            },
        )

    # ------------------------------------------------------------------ #
    # HolmesGPT MCP
    # ------------------------------------------------------------------ #

    async def _call_holmesgpt_mcp(self, token: str, finding: Finding) -> dict:
        async with httpx.AsyncClient(
            base_url=_HOLMES_MCP_URL,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type":  "application/json"},
            timeout=_HOLMES_TIMEOUT,
        ) as client:
            resp = await client.post(
                "/mcp/tool",
                json={
                    "tool": "investigate_alert",
                    "input": {
                        "alert_name":  finding.title,
                        "labels":      self._extract_labels(finding),
                        "description": finding.description,
                        "severity":    finding.severity,
                        "artifact":    finding.artifact,
                    },
                },
            )
            resp.raise_for_status()
            body = resp.json()

        if body.get("error"):
            raise RuntimeError(f"HolmesGPT MCP error: {body['error']}")
        return self._parse_holmesgpt_response(body.get("result", {}), finding)

    @staticmethod
    def _extract_labels(finding: Finding) -> dict:
        """Build Prometheus-style labels from Finding for HolmesGPT context."""
        labels: dict = {}
        raw = finding.raw or {}
        if "labels" in raw and isinstance(raw["labels"], dict):
            labels = dict(raw["labels"])
        if finding.repository:
            labels.setdefault("repository", finding.repository)
        if finding.artifact:
            labels.setdefault("artifact", finding.artifact)
        labels.setdefault("severity", finding.severity.lower())
        return labels

    @staticmethod
    def _parse_holmesgpt_response(raw: dict, finding: Finding) -> dict:
        """Normalise HolmesGPT response → standard result dict."""
        root_cause = raw.get("root_cause") or (
            f"HolmesGPT investigated '{finding.title}' — see evidence for details."
        )
        suggested_fix = raw.get("suggested_fix") or (
            "Review the evidence entries and apply the runbook steps."
        )
        evidence = raw.get("evidence", [])
        runbooks = raw.get("runbooks", [])

        if evidence:
            summary = "\n".join(
                f"  [{e.get('type', '?')}] {str(e.get('content', ''))[:120]}"
                for e in evidence[:4]
            )
            root_cause += f"\n\nEvidence:\n{summary}"

        return {
            "root_cause":    root_cause,
            "suggested_fix": suggested_fix,
            "evidence":      evidence,
            "runbooks":      runbooks,
        }

    # ------------------------------------------------------------------ #
    # Heuristic fallback
    # ------------------------------------------------------------------ #

    @staticmethod
    def _heuristic_analyse(finding: Finding) -> dict:
        haystack = f"{finding.title} {finding.description}".lower()
        for pattern, root_cause, fix in _HEURISTIC_RULES:
            if re.search(pattern, haystack, re.IGNORECASE):
                return {"root_cause": root_cause,
                        "suggested_fix": fix,
                        "pattern": pattern}
        return {
            "root_cause": (
                f"Alert '{finding.title}' on '{finding.artifact}' requires "
                "manual investigation — no matching heuristic pattern found."
            ),
            "suggested_fix": (
                "Run `kubectl describe pod` / `kubectl logs` for the affected workload. "
                "Check Prometheus and Grafana dashboards for correlated metric spikes."
            ),
            "pattern": "generic",
        }
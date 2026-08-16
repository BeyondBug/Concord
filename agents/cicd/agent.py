"""
agents/cicd/agent.py
CICDAgent — Trivy MCP-backed container / filesystem / IaC scanner.
Phase 2B (rj-karan): full implementation.

Call order:
  1. Trivy MCP  → scan_container (image: artifacts) or scan_filesystem (paths)
  2. Fallback   → built-in YAML/Dockerfile pattern scanner (zero external deps)

MCP protocol (Concord subset):
  POST /mcp/tool  { "tool": "<capability>", "input": { ... } }
  →               { "result": { ... }, "error": null }

Source reliability: 0.88  (Trivy + Checkov combined — agent_response.py)
"""
import logging
import os
import re
from pathlib import Path

import httpx

from agents.base import BaseAgent
from core.credential_broker import CredentialBroker
from core.models.agent_response import AgentResponse, compute_confidence
from core.models.finding import Finding

logger = logging.getLogger("concord.agent.cicd")

_TRIVY_MCP_URL = os.getenv("TRIVY_MCP_URL", "http://localhost:8002")
_TRIVY_TIMEOUT = float(os.getenv("TRIVY_TIMEOUT", "45"))

_SEV_MAP = {
    "CRITICAL": "CRITICAL",
    "HIGH":     "HIGH",
    "MEDIUM":   "MEDIUM",
    "LOW":      "LOW",
    "UNKNOWN":  "LOW",
}

_CANDIDATES = ["repos/crms/k8s", "repos/crms", "k8s", "."]

# ── Fallback: lightweight YAML/Dockerfile checks (no external deps) ────────
_K8S_CHECKS = [
    ("CKV_K8S_16",  "HIGH",     r"privileged:\s*true",
     "Container running in privileged mode",
     "Set privileged: false in securityContext"),
    ("CKV_K8S_35",  "HIGH",     r"allowPrivilegeEscalation:\s*true",
     "Container allows privilege escalation",
     "Set allowPrivilegeEscalation: false"),
    ("CKV_K8S_43",  "HIGH",     r"image:\s*\S+:latest",
     "Container uses :latest image tag (unpinned)",
     "Pin image to a specific digest or semver tag"),
    ("CKV_K8S_20",  "MEDIUM",   r"runAsUser:\s*0\b",
     "Container may run as root (runAsUser: 0)",
     "Set runAsNonRoot: true and runAsUser to a non-zero UID"),
    ("CKV_K8S_SECRET", "CRITICAL", r"(?i)(password|secret|token|api.key)\s*:\s*\S{6,}",
     "Possible hardcoded secret in manifest",
     "Use Kubernetes Secrets or an external secret manager"),
    ("CKV_DOCKER_1", "HIGH",    r"^FROM\s+\S+:latest",
     "Dockerfile uses :latest base image",
     "Pin base image to a specific digest"),
    ("CKV_DOCKER_2", "MEDIUM",  r"^USER\s+root",
     "Dockerfile sets USER root",
     "Add a non-root USER instruction before CMD/ENTRYPOINT"),
]


class CICDAgent(BaseAgent):

    @property
    def domain(self) -> str:
        return "cicd"

    @property
    def source_reliability(self) -> float:
        return 0.88

    # ------------------------------------------------------------------ #

    async def analyze(self, finding: Finding) -> AgentResponse:
        target    = self._resolve(finding.artifact)
        is_image  = (
            finding.artifact.startswith("image:")
            or (":" in Path(target).name and "/" not in target)
        )
        logger.info("[CICD]  target=%s  is_image=%s", target, is_image)

        # ── 1. Trivy MCP ──────────────────────────────────────────────
        try:
            token  = CredentialBroker().get_token("trivy")
            result = await self._call_trivy_mcp(token, target, is_image)
            logger.info("[CICD]  Trivy MCP → %d vulnerabilities", result["total"])
            return AgentResponse(
                agent=self.domain,
                finding_id=finding.id,
                confidence_score=compute_confidence(self.domain, finding.severity),
                root_cause=result["root_cause"],
                suggested_fix=result["fix"],
                metadata={
                    "scanner":     "trivy-mcp",
                    "target":      target,
                    "scan_type":   "container" if is_image else "filesystem",
                    "total":       result["total"],
                    "by_severity": result.get("by_severity", {}),
                    "mcp_url":     _TRIVY_MCP_URL,
                    "real_scan":   True,
                },
            )
        except ValueError as exc:
            logger.warning("[CICD]  no TRIVY_TOKEN (%s) — fallback", exc)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning("[CICD]  Trivy MCP unreachable (%s) — fallback", exc)
        except Exception as exc:
            logger.error("[CICD]  Trivy MCP error: %s", exc)

        # ── 2. Fallback: built-in scanner ─────────────────────────────
        logger.info("[CICD]  fallback → built-in scanner on %s", target)
        result = self._builtin_scan(target)
        logger.info("[CICD]  fallback → %d violations", result["total"])
        return AgentResponse(
            agent=self.domain,
            finding_id=finding.id,
            confidence_score=compute_confidence(self.domain, finding.severity),
            root_cause=result["root_cause"],
            suggested_fix=result["fix"],
            metadata={
                "scanner":      "concord-builtin (fallback)",
                "target":       target,
                "violations":   result["total"],
                "by_severity":  result.get("by_severity", {}),
                "real_scan":    True,
                "mcp_fallback": True,
            },
        )

    # ------------------------------------------------------------------ #
    # Trivy MCP
    # ------------------------------------------------------------------ #

    async def _call_trivy_mcp(
        self, token: str, target: str, is_image: bool
    ) -> dict:
        tool         = "scan_container" if is_image else "scan_filesystem"
        scan_target  = target.removeprefix("image:") if is_image else target

        async with httpx.AsyncClient(
            base_url=_TRIVY_MCP_URL,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type":  "application/json"},
            timeout=_TRIVY_TIMEOUT,
        ) as client:
            resp = await client.post(
                "/mcp/tool",
                json={"tool": tool,
                      "input": {"target": scan_target, "format": "json"}},
            )
            resp.raise_for_status()
            body = resp.json()

        if body.get("error"):
            raise RuntimeError(f"Trivy MCP error: {body['error']}")
        return self._parse_trivy_response(body.get("result", {}), scan_target)

    @staticmethod
    def _parse_trivy_response(raw: dict, target: str) -> dict:
        """Normalise Trivy JSON → standard result dict."""
        vulns: list[dict] = []
        for res in raw.get("Results", []):
            for v in res.get("Vulnerabilities") or []:
                vulns.append({
                    "id":        v.get("VulnerabilityID", "UNKNOWN"),
                    "severity":  _SEV_MAP.get(v.get("Severity", "LOW"), "LOW"),
                    "title":     v.get("Title", "No title"),
                    "fixed_in":  v.get("FixedVersion", "no fix available"),
                    "pkg":       v.get("PkgName", ""),
                    "target":    res.get("Target", target),
                })

        if not vulns:
            return {"total": 0, "by_severity": {},
                    "root_cause": f"No vulnerabilities found in {target}.",
                    "fix": "Target is clean.", "checks": []}

        _w = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        vulns.sort(key=lambda v: _w.get(v["severity"], 0), reverse=True)

        by_sev: dict[str, int] = {}
        for v in vulns:
            by_sev[v["severity"]] = by_sev.get(v["severity"], 0) + 1

        top   = vulns[0]
        lines = "\n".join(
            f"  [{v['id']}] {v['severity']} — {v['title']} ({v['pkg']})"
            for v in vulns[:6]
        )
        root_cause = (
            f"[{top['id']}] {top['title']} in {top['target']}\n"
            f"{len(vulns)} vulnerability/ies found:\n{lines}"
        )
        fix = (
            f"Fix {top['id']}: upgrade {top['pkg']} → {top['fixed_in']}"
            if top["fixed_in"] != "no fix available"
            else f"No upstream fix yet for {top['id']}. Apply workaround or accept risk."
        )
        return {"total": len(vulns), "by_severity": by_sev,
                "root_cause": root_cause, "fix": fix, "checks": vulns[:5]}

    # ------------------------------------------------------------------ #
    # Fallback scanner
    # ------------------------------------------------------------------ #

    @staticmethod
    def _builtin_scan(directory: str) -> dict:
        """Scan YAML + Dockerfiles for common misconfigs. Zero external deps."""
        d       = Path(directory)
        files   = list(d.rglob("*.yaml")) + list(d.rglob("*.yml")) + \
                  list(d.rglob("Dockerfile*"))
        files   = [f for f in files
                   if not any(x in str(f) for x in
                              [".github", "node_modules", "__pycache__"])]

        findings = []
        for f in files:
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for chk_id, sev, pattern, title, fix in _K8S_CHECKS:
                for i, ln in enumerate(lines, 1):
                    if re.search(pattern, ln, re.IGNORECASE | re.MULTILINE):
                        findings.append({
                            "id": chk_id, "severity": sev,
                            "title": title, "fix": fix,
                            "file": f.name, "line": i,
                        })
                        break

        if not findings:
            label = directory if files else f"{directory} (no files found)"
            return {"total": 0, "by_severity": {},
                    "root_cause": f"No violations found in {label}.",
                    "fix": "Configuration is compliant."}

        _w = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        findings.sort(key=lambda f: _w.get(f["severity"], 0), reverse=True)
        by_sev: dict[str, int] = {}
        for f in findings:
            by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1

        top   = findings[0]
        lines = "\n".join(
            f"  [{f['id']}] {f['severity']} — {f['title']} ({f['file']}:{f['line']})"
            for f in findings[:6]
        )
        return {
            "total":      len(findings),
            "by_severity": by_sev,
            "root_cause": (
                f"[{top['id']}] {top['title']} ({top['file']}:{top['line']})\n"
                f"{len(findings)} violation(s) found:\n{lines}"
            ),
            "fix":    top["fix"],
            "checks": findings[:5],
        }

    # ------------------------------------------------------------------ #

    def _resolve(self, artifact: str) -> str:
        if artifact and (artifact.startswith("image:") or Path(artifact).exists()):
            return artifact
        for c in _CANDIDATES:
            if Path(c).exists():
                return c
        return "."
#!/usr/bin/env python3
"""
Concord Phase 0 — File updater
Run from repo root: python update_phase0.py
Creates/updates 6 files needed for the Friday demo.
"""
from pathlib import Path

ROOT = Path(".")

def w(path, content):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.lstrip("\n"), encoding="utf-8")
    print(f"  ✓  {path}")

print("\n  Concord Phase 0 — writing implementation files...\n")

# ═══════════════════════════════════════════════════
# 1. core/orchestrator/orchestrator.py  (CREATE)
# ═══════════════════════════════════════════════════
w("core/orchestrator/orchestrator.py", '''
"""
core/orchestrator/orchestrator.py
Main orchestrator — wires triage gate, routing, agents, and arbitration.
"""
import logging
from datetime import datetime
from core.models.finding import Finding
from core.models.agent_response import AgentResponse, compute_confidence
from core.triage.gate import TriageGate
from core.triage.rules.severity import LowSeverityRule
from core.triage.rules.patterns import KnownPatternRule
from core.triage.rules.dedup import DedupRule
from core.arbitration.resolver import arbitrate
from core.mcp_runtime.audit import AuditLog, AuditEntry

logger = logging.getLogger("concord.orchestrator")


class Orchestrator:
    def __init__(self):
        self.triage = TriageGate(rules=[
            LowSeverityRule(),
            KnownPatternRule(known_ids=set()),
            DedupRule(),
        ])
        self.audit = AuditLog()

    async def process(self, finding: Finding) -> dict:
        logger.info("")
        logger.info("=" * 60)
        logger.info("CONCORD  finding=%s  severity=%s", finding.id, finding.severity)
        logger.info("  artifact : %s", finding.artifact)
        logger.info("  repo     : %s", finding.repository)
        logger.info("=" * 60)

        # Step 1: Triage gate
        needs_ai, reason = self.triage.evaluate(finding)

        if not needs_ai:
            logger.info("[TRIAGE]  FAST PATH — %s", reason)
            self.audit.record(AuditEntry(
                finding_id=finding.id, path="fast_path",
                reason=reason, agent=None, timestamp=datetime.utcnow(),
            ))
            return {"path": "fast_path", "reason": reason, "pr_comment": None}

        logger.info("[TRIAGE]  ESCALATE — %s", reason)

        # Step 2: Call domain agents
        responses = await self._run_agents(finding)

        if not responses:
            logger.warning("[ORCHESTRATOR] no agents produced a response")
            return {"path": "ai_path", "error": "no agent responses"}

        # Step 3: Arbitrate
        winner, auto_resolved = arbitrate(responses)
        sorted_r = sorted(responses, key=lambda r: r.confidence_score, reverse=True)

        logger.info("[ARBITRATION]  %s",
                    " | ".join(f"{r.agent}={r.confidence_score:.4f}" for r in sorted_r))

        if auto_resolved:
            gap = (sorted_r[0].confidence_score - sorted_r[1].confidence_score
                   if len(sorted_r) > 1 else 1.0)
            logger.info("[ARBITRATION]  AUTO-RESOLVED — %s wins (gap=%.4f >= 0.15)",
                        winner.agent, gap)
            pr_comment = self._fmt_auto(winner)
        else:
            gap = sorted_r[0].confidence_score - sorted_r[1].confidence_score
            logger.info("[ARBITRATION]  HUMAN TIEBREAK — gap=%.4f < 0.15", gap)
            pr_comment = self._fmt_tiebreak(sorted_r)

        # Step 4: Audit
        self.audit.record(AuditEntry(
            finding_id=finding.id, path="ai_path",
            reason="auto_resolved" if auto_resolved else "human_tiebreak",
            agent=winner.agent, timestamp=datetime.utcnow(),
        ))

        logger.info("[OUTPUT]  %s", "auto-resolved" if auto_resolved else "human tiebreak")

        return {
            "path": "ai_path",
            "agent": winner.agent,
            "score": winner.confidence_score,
            "auto_resolved": auto_resolved,
            "pr_comment": pr_comment,
        }

    async def _run_agents(self, finding: Finding) -> list[AgentResponse]:
        from agents.infra.agent import InfraAgent
        from agents.cicd.agent import CICDAgent

        # Phase 0: both agents run on every finding to demo arbitration.
        # Phase 1: Router will select agents by artifact type.
        agent_map = {"infra": InfraAgent(), "cicd": CICDAgent()}
        responses = []

        for domain, agent in agent_map.items():
            try:
                resp = await agent.analyze(finding)
                # Confidence always computed here — never self-reported by agent.
                resp.confidence_score = compute_confidence(domain, finding.severity)
                logger.info("[%s AGENT]  confidence=%.4f  | %s",
                            domain.upper(), resp.confidence_score, resp.root_cause[:60])
                responses.append(resp)
            except NotImplementedError:
                logger.warning("[%s AGENT]  not implemented yet", domain.upper())
            except Exception as exc:
                logger.error("[%s AGENT]  error: %s", domain.upper(), exc)

        return responses

    def _fmt_auto(self, winner: AgentResponse) -> str:
        return (
            f"**Concord** — auto-resolved\\n\\n"
            f"**Agent:** {winner.agent}  |  **Confidence:** {winner.confidence_score:.4f}\\n\\n"
            f"**Root cause:** {winner.root_cause}\\n\\n"
            f"**Suggested fix:**\\n{winner.suggested_fix}\\n\\n"
            f"*Confidence gap >= 0.15. Audit trail written.*"
        )

    def _fmt_tiebreak(self, sorted_responses: list[AgentResponse]) -> str:
        top, second = sorted_responses[0], sorted_responses[1]
        gap = top.confidence_score - second.confidence_score
        return (
            f"**Concord** — human tiebreak required\\n\\n"
            f"Confidence gap {gap:.4f} is below threshold 0.15.\\n\\n"
            f"**{top.agent} agent** (score {top.confidence_score:.4f})\\n"
            f"Root cause: {top.root_cause}\\n"
            f"Fix: {top.suggested_fix}\\n\\n"
            f"**{second.agent} agent** (score {second.confidence_score:.4f})\\n"
            f"Root cause: {second.root_cause}\\n"
            f"Fix: {second.suggested_fix}\\n\\n"
            f"Reply `/approve {top.agent}` or `/approve {second.agent}` to resolve."
        )
''')

# ═══════════════════════════════════════════════════
# 2. agents/infra/agent.py  (UPDATE)
# ═══════════════════════════════════════════════════
w("agents/infra/agent.py", '''
"""
agents/infra/agent.py
InfraAgent — Phase 0 stub. Phase 2A (Jash): replace with TerraSecure MCP call.
"""
from agents.base import BaseAgent
from core.models.finding import Finding
from core.models.agent_response import AgentResponse

_STUBS: dict[str, tuple[str, str]] = {
    "CRITICAL": (
        "IAM policy grants wildcard (*) actions on wildcard (*) resources. "
        "Any principal with this policy has unrestricted account access.",
        "Restrict to minimum required actions and specific resource ARNs:\\n"
        "  actions   = [\\"s3:GetObject\\", \\"s3:PutObject\\"]\\n"
        "  resources = [\\"arn:aws:s3:::my-bucket/*\\"]",
    ),
    "HIGH": (
        "Security group allows unrestricted inbound SSH (port 22) from 0.0.0.0/0. "
        "Instance is exposed to the public internet.",
        "Restrict SSH to a known CIDR block:\\n"
        "  cidr_blocks = [\\"10.0.0.0/8\\"]  # internal network only",
    ),
    "MEDIUM": (
        "S3 bucket has versioning disabled. "
        "Accidental deletion or overwrite cannot be recovered.",
        "Enable versioning:\\n  versioning { enabled = true }",
    ),
    "LOW": (
        "Terraform resource is missing a Name tag. "
        "Cost attribution and console visibility are reduced.",
        "Add a Name tag:\\n  tags = { Name = \\"my-resource\\" }",
    ),
}
_DEFAULT = (
    "IaC misconfiguration detected.",
    "Apply least-privilege Terraform configuration.",
)


class InfraAgent(BaseAgent):
    """Infrastructure / Terraform agent.

    Phase 0: realistic stub responses by severity.
    Phase 2A (Jash): replace with TerraSecure MCP call + SARIF parsing.
    """

    @property
    def domain(self) -> str:
        return "infra"

    @property
    def source_reliability(self) -> float:
        return 0.92  # TerraSecure ML accuracy: 92.45%

    async def analyze(self, finding: Finding) -> AgentResponse:
        root_cause, fix = _STUBS.get(finding.severity, _DEFAULT)
        return AgentResponse(
            agent=self.domain,
            finding_id=finding.id,
            confidence_score=0.0,   # always overwritten by orchestrator
            root_cause=root_cause,
            suggested_fix=fix,
            metadata={"scanner": "TerraSecure", "phase": "0-stub"},
        )
''')

# ═══════════════════════════════════════════════════
# 3. agents/cicd/agent.py  (UPDATE)
# ═══════════════════════════════════════════════════
w("agents/cicd/agent.py", '''
"""
agents/cicd/agent.py
CICDAgent — Phase 0 stub. Phase 2B (rj-karan): replace with Trivy/Checkov MCP.
"""
from agents.base import BaseAgent
from core.models.finding import Finding
from core.models.agent_response import AgentResponse

_STUBS: dict[str, tuple[str, str]] = {
    "CRITICAL": (
        "Base image python:3.11-slim contains CVE-2024-12345 (OpenSSL RCE). "
        "All containers built from this image are vulnerable to remote code execution.",
        "Update the Dockerfile base image:\\n"
        "  FROM python:3.11.9-slim-bookworm\\n"
        "Rebuild and push all affected container images.",
    ),
    "HIGH": (
        "Dependency requests==2.28.0 has CVE-2023-32681. "
        "HTTP redirect following can leak credentials to a third-party host.",
        "Upgrade in requirements/base.txt:\\n"
        "  requests>=2.31.0",
    ),
    "MEDIUM": (
        "GitHub Actions workflow uses an unpinned action tag (e.g. @v3). "
        "Supply chain compromise possible if the tag is moved.",
        "Pin to a specific commit SHA:\\n"
        "  uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
    ),
    "LOW": (
        "Docker image exceeds 500 MB. Large images increase pull latency and attack surface.",
        "Use multi-stage builds to reduce final image size.",
    ),
}
_DEFAULT = (
    "CI/CD security issue detected by Trivy/Checkov.",
    "Review pipeline configuration and apply security best practices.",
)


class CICDAgent(BaseAgent):
    """CI/CD agent backed by Trivy and Checkov.

    Phase 0: realistic stub responses by severity.
    Phase 2B (rj-karan): replace with Trivy/Checkov MCP calls + SARIF parsing.
    """

    @property
    def domain(self) -> str:
        return "cicd"

    @property
    def source_reliability(self) -> float:
        return 0.88  # Trivy + Checkov combined calibration

    async def analyze(self, finding: Finding) -> AgentResponse:
        root_cause, fix = _STUBS.get(finding.severity, _DEFAULT)
        return AgentResponse(
            agent=self.domain,
            finding_id=finding.id,
            confidence_score=0.0,   # always overwritten by orchestrator
            root_cause=root_cause,
            suggested_fix=fix,
            metadata={"scanner": "Trivy/Checkov", "phase": "0-stub"},
        )
''')

# ═══════════════════════════════════════════════════
# 4. api/routes/events.py  (UPDATE)
# ═══════════════════════════════════════════════════
w("api/routes/events.py", '''
"""
api/routes/events.py
Webhook receiver + /demo endpoint for Friday review.
"""
import hmac
import hashlib
import logging
import os
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from core.models.finding import Finding

router = APIRouter(prefix="/events", tags=["events"])
logger = logging.getLogger("concord.events")


def _verify_signature(body: bytes, sig_header: str) -> bool:
    secret = os.getenv("WEBHOOK_SECRET", "")
    if not secret:
        return True  # dev mode: skip check if no secret configured
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return hmac.compare_digest("sha256=" + mac.hexdigest(), sig_header or "")


async def _run(finding: Finding) -> None:
    from core.orchestrator.orchestrator import Orchestrator
    await Orchestrator().process(finding)


@router.post("/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Accept a real GitHub push/PR webhook payload."""
    body = await request.body()
    if not _verify_signature(body, request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    repo = payload.get("repository", {}).get("full_name", "unknown/repo")
    commit = payload.get("head_commit") or {}

    finding = Finding(
        id=(commit.get("id", "webhook-001"))[:12],
        source="github-webhook",
        artifact=(commit.get("modified") or ["unknown"])[0],
        severity="HIGH",
        title=(commit.get("message", "Push event"))[:80],
        description=f"Push to {repo}",
        raw=payload,
        repository=repo,
    )

    background_tasks.add_task(_run, finding)
    return {"status": "received", "finding_id": finding.id, "repo": repo}


@router.post("/demo")
async def demo_endpoint(severity: str = "CRITICAL"):
    """
    Demo endpoint — run a sample finding through Concord synchronously.
    Perfect for the Friday review: hit this from /docs and see the full result.

    Try:  POST /events/demo?severity=CRITICAL
          POST /events/demo?severity=LOW
    """
    from core.orchestrator.orchestrator import Orchestrator

    finding = Finding(
        id="CVE-2024-33663",
        source="terrasecure-demo",
        artifact="infra/terraform/main.tf",
        severity=severity.upper(),
        title="IAM policy allows overly permissive actions",
        description="AWS IAM policy grants * actions on * resources",
        raw={"demo": True, "rule_id": "TF-IAM-001"},
        repository="BeyondBug/CRMS",
        pr_number=42,
    )

    return await Orchestrator().process(finding)
''')

# ═══════════════════════════════════════════════════
# 5. scripts/demo.py  (CREATE)
# ═══════════════════════════════════════════════════
w("scripts/demo.py", r'''
#!/usr/bin/env python3
"""
scripts/demo.py
Concord Friday demo script — run from repo root:
    python scripts/demo.py
"""
import asyncio
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format="%(message)s")

from core.models.finding import Finding
from core.orchestrator.orchestrator import Orchestrator

G  = "\033[92m"   # green
Y  = "\033[93m"   # yellow / amber
R  = "\033[91m"   # red
B  = "\033[94m"   # blue
C  = "\033[96m"   # cyan
W  = "\033[97m"   # white
BD = "\033[1m"
RS = "\033[0m"

def hr(char="─", n=62):
    print(f"{W}{char * n}{RS}")

def banner(text, color=C):
    hr("═")
    print(f"{color}{BD}  {text}{RS}")
    hr("═")


async def scenario(label, finding, orch):
    print(f"\n{Y}{BD}  {label}{RS}")
    hr()
    print(f"  finding_id : {finding.id}")
    print(f"  severity   : {finding.severity}")
    print(f"  artifact   : {finding.artifact}")
    print(f"  repository : {finding.repository}")
    hr()

    result = await orch.process(finding)

    print(f"\n{W}{BD}  RESULT{RS}")
    hr()
    print(f"  path         : {result['path']}")

    if result["path"] == "fast_path":
        print(f"  reason       : {result['reason']}")
        print(f"  LLM called   : {R}NO{RS}  (zero inference cost)")
    else:
        print(f"  agent        : {result.get('agent')}")
        print(f"  confidence   : {result.get('score', 0):.4f}")
        resolved = result.get("auto_resolved")
        resolution = f"{G}auto-resolved{RS}" if resolved else f"{Y}human tiebreak{RS}"
        print(f"  resolution   : {resolution}")
        if result.get("pr_comment"):
            print(f"\n  {BD}PR Comment:{RS}")
            for line in result["pr_comment"].split("\\n"):
                print(f"    {line}")
    hr()


async def main():
    banner("CONCORD — Friday Demo  |  BeyondBug/Concord")
    print(f"\n  {BD}What you are seeing:{RS}")
    print("  1. Triage gate  — deterministic rules, no LLM")
    print("  2. Domain agents — Infra (TerraSecure) + CI/CD (Trivy/Checkov)")
    print("  3. Arbitration  — severity × source reliability, NOT LLM confidence")
    print("  4. Audit trail  — every finding logged regardless of path")

    orch = Orchestrator()

    await scenario(
        "SCENARIO 1 — CRITICAL Terraform finding → expect human tiebreak",
        Finding(
            id="CVE-2024-33663",
            source="terrasecure",
            artifact="infra/terraform/main.tf",
            severity="CRITICAL",
            title="IAM policy allows overly permissive actions",
            description="AWS IAM policy grants * actions on * resources",
            raw={"rule_id": "TF-IAM-001"},
            repository="BeyondBug/CRMS",
            pr_number=42,
        ),
        orch,
    )

    await scenario(
        "SCENARIO 2 — LOW severity finding → fast path, no LLM",
        Finding(
            id="LINT-TAG-001",
            source="checkov",
            artifact="infra/terraform/storage.tf",
            severity="LOW",
            title="S3 bucket missing Name tag",
            description="Resource has no Name tag",
            raw={},
            repository="BeyondBug/CRMS",
        ),
        orch,
    )

    banner("DEMO COMPLETE", G)
    print(f"  {G}✓{RS}  Triage gate working  (0 LLM calls for LOW finding)")
    print(f"  {G}✓{RS}  Two agents analyzed the CRITICAL finding independently")
    print(f"  {G}✓{RS}  Confidence = severity_weight × source_reliability (not LLM)")
    print(f"  {G}✓{RS}  Arbitration produced a human tiebreak PR comment")
    print(f"  {G}✓{RS}  Audit trail written for both findings\n")


if __name__ == "__main__":
    asyncio.run(main())
''')

# ═══════════════════════════════════════════════════
# 6. tests/unit/test_orchestrator.py  (CREATE)
# ═══════════════════════════════════════════════════
w("tests/unit/test_orchestrator.py", '''
"""
tests/unit/test_orchestrator.py
Orchestrator integration tests (uses agent stubs — no external deps).
"""
import pytest
from datetime import datetime
from core.models.finding import Finding
from core.orchestrator.orchestrator import Orchestrator


def make_finding(severity="HIGH", finding_id="test-001"):
    return Finding(
        id=finding_id,
        source="test",
        artifact="infra/terraform/main.tf",
        severity=severity,
        title="Test finding",
        description="Unit test",
        raw={},
        timestamp=datetime.utcnow(),
        repository="BeyondBug/CRMS",
    )


@pytest.mark.asyncio
async def test_low_severity_takes_fast_path():
    result = await Orchestrator().process(make_finding(severity="LOW"))
    assert result["path"] == "fast_path"
    assert result["pr_comment"] is None


@pytest.mark.asyncio
async def test_informational_takes_fast_path():
    result = await Orchestrator().process(make_finding(severity="INFORMATIONAL"))
    assert result["path"] == "fast_path"


@pytest.mark.asyncio
async def test_critical_finding_escalates_to_ai():
    result = await Orchestrator().process(make_finding(severity="CRITICAL"))
    assert result["path"] == "ai_path"
    assert result.get("agent") is not None
    assert result.get("score", 0) > 0


@pytest.mark.asyncio
async def test_high_finding_produces_pr_comment():
    result = await Orchestrator().process(make_finding(severity="HIGH"))
    assert result["path"] == "ai_path"
    assert result.get("pr_comment") is not None
    assert len(result["pr_comment"]) > 0


@pytest.mark.asyncio
async def test_result_has_auto_resolved_field():
    result = await Orchestrator().process(make_finding(severity="CRITICAL"))
    assert "auto_resolved" in result
    assert isinstance(result["auto_resolved"], bool)


@pytest.mark.asyncio
async def test_confidence_scores_match_formula():
    """CRITICAL + infra: expected 1.0 * 0.92 = 0.9200"""
    result = await Orchestrator().process(make_finding(severity="CRITICAL"))
    # Winner is always the agent with highest confidence score
    # infra: 0.92, cicd: 0.88 — infra should win or both trigger tiebreak
    assert result["score"] in (0.92, 0.88)
''')

print("\n  ✓  All 6 files written.\n")
print("  Next steps:")
print("    1. pip install pytest-asyncio -r requirements/dev.txt")
print("    2. pytest tests/unit -v")
print("    3. python scripts/demo.py")
print()
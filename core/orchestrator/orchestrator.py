"""
core/orchestrator/orchestrator.py
Main orchestrator — triage → agents → arbitration → LLM → store.
"""
import logging
import os
from datetime import datetime

from core.arbitration.resolver import arbitrate
from core.mcp_runtime.audit import AuditEntry, AuditLog
from core.models.agent_response import AgentResponse, compute_confidence
from core.models.finding import Finding
from core.triage.gate import TriageGate
from core.triage.rules.dedup import DedupRule
from core.triage.rules.patterns import KnownPatternRule
from core.triage.rules.severity import LowSeverityRule

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
        logger.info("=" * 60)
        logger.info("CONCORD  %s  severity=%s  artifact=%s",
                    finding.id, finding.severity, finding.artifact)

        # ── Step 1: Triage ────────────────────────────────────────
        needs_ai, reason = self.triage.evaluate(finding)

        if not needs_ai:
            logger.info("[TRIAGE]  FAST PATH — %s", reason)
            result = {"path": "fast_path", "reason": reason, "pr_comment": None}
            self._store(finding, result)
            self.audit.record(AuditEntry(
                finding_id=finding.id, path="fast_path",
                reason=reason, agent=None, timestamp=datetime.utcnow(),
            ))
            return result

        logger.info("[TRIAGE]  ESCALATE — %s", reason)

        # ── Step 2: Agents ────────────────────────────────────────
        responses = await self._run_agents(finding)
        if not responses:
            return {"path": "ai_path", "error": "no agent responses"}

        # ── Step 3: Arbitrate ─────────────────────────────────────
        winner, auto_resolved = arbitrate(responses)
        sorted_r = sorted(responses, key=lambda r: r.confidence_score, reverse=True)
        scores = " | ".join(f"{r.agent}={r.confidence_score:.4f}" for r in sorted_r)
        logger.info("[ARBITRATION]  %s", scores)

        if auto_resolved:
            gap = (sorted_r[0].confidence_score - sorted_r[1].confidence_score
                   if len(sorted_r) > 1 else 1.0)
            logger.info("[ARBITRATION]  AUTO-RESOLVED  %s wins (gap=%.4f)",
                        winner.agent, gap)
        else:
            gap = sorted_r[0].confidence_score - sorted_r[1].confidence_score
            logger.info("[ARBITRATION]  HUMAN TIEBREAK  gap=%.4f < 0.15", gap)

        # ── Step 4: LLM PR comment ────────────────────────────────
        pr_comment = await self._build_pr_comment(
            finding, sorted_r, auto_resolved, winner
        )

        # ── Step 5: Audit + store ─────────────────────────────────
        result = {
            "path": "ai_path",
            "agent": winner.agent,
            "score": winner.confidence_score,
            "auto_resolved": auto_resolved,
            "pr_comment": pr_comment,
        }
        self._store(finding, result)
        self.audit.record(AuditEntry(
            finding_id=finding.id, path="ai_path",
            reason="auto_resolved" if auto_resolved else "human_tiebreak",
            agent=winner.agent, timestamp=datetime.utcnow(),
        ))
        logger.info("[OUTPUT]  %s", "auto-resolved" if auto_resolved else "human tiebreak")
        return result

    # ── Helpers ───────────────────────────────────────────────────

    async def _run_agents(self, finding: Finding) -> list[AgentResponse]:
        from agents.cicd.agent import CICDAgent
        from agents.infra.agent import InfraAgent

        responses = []
        for domain, agent in [("infra", InfraAgent()), ("cicd", CICDAgent())]:
            try:
                resp = await agent.analyze(finding)
                resp.confidence_score = compute_confidence(domain, finding.severity)
                logger.info("[%s]  confidence=%.4f  %s",
                            domain.upper(), resp.confidence_score, resp.root_cause[:55])
                responses.append(resp)
            except NotImplementedError:
                logger.warning("[%s]  not implemented yet", domain.upper())
            except Exception as exc:
                logger.error("[%s]  error: %s", domain.upper(), exc)
        return responses

    async def _build_pr_comment(self, finding: Finding,
                                sorted_r: list[AgentResponse],
                                auto_resolved: bool,
                                winner: AgentResponse) -> str:
        """Use LLM if configured, otherwise use stub responses."""
        provider = os.getenv("LLM_PROVIDER", "ollama")
        use_llm = provider in ("openai", "nvidia_nim") or (
            provider == "ollama" and os.getenv("OLLAMA_BASE_URL")
        )

        if use_llm:
            try:
                from core.orchestrator.llm import LLMBackend
                llm = LLMBackend()
                analysis = await llm.generate_analysis(
                    finding_id=finding.id,
                    severity=finding.severity,
                    artifact=finding.artifact,
                    title=finding.title,
                    description=finding.description,
                )
                if analysis.get("root_cause"):
                    winner.root_cause = analysis["root_cause"]
                    winner.suggested_fix = analysis["suggested_fix"]
                    logger.info("[LLM]  %s analysis generated", provider)
            except Exception as exc:
                logger.warning("[LLM]  failed, using stub: %s", exc)

        if auto_resolved:
            return (
                f"**Concord** — auto-resolved\n\n"
                f"**Agent:** {winner.agent}  |  "
                f"**Confidence:** {winner.confidence_score:.4f}\n\n"
                f"**Root cause:** {winner.root_cause}\n\n"
                f"**Suggested fix:**\n{winner.suggested_fix}\n\n"
                f"*Confidence gap ≥ 0.15. Audit trail written.*"
            )
        else:
            top, second = sorted_r[0], sorted_r[1]
            gap = top.confidence_score - second.confidence_score
            return (
                f"**Concord** — human tiebreak required\n\n"
                f"Confidence gap **{gap:.4f}** is below threshold 0.15.\n\n"
                f"**{top.agent} agent** (score {top.confidence_score:.4f})\n"
                f"Root cause: {top.root_cause}\n"
                f"Fix: {top.suggested_fix}\n\n"
                f"**{second.agent} agent** (score {second.confidence_score:.4f})\n"
                f"Root cause: {second.root_cause}\n"
                f"Fix: {second.suggested_fix}\n\n"
                f"Reply `/approve {top.agent}` or `/approve {second.agent}` to resolve."
            )

    def _store(self, finding: Finding, result: dict) -> None:
        try:
            from api.routes.findings import store
            store.add(
                finding_id=finding.id,
                severity=finding.severity,
                artifact=finding.artifact,
                repo=finding.repository,
                source=finding.source,
                path=result["path"],
                result=result,
            )
        except Exception:
            pass  # store is optional

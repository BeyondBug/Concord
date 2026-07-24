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
            f"**Concord** — auto-resolved\n\n"
            f"**Agent:** {winner.agent}  |  **Confidence:** {winner.confidence_score:.4f}\n\n"
            f"**Root cause:** {winner.root_cause}\n\n"
            f"**Suggested fix:**\n{winner.suggested_fix}\n\n"
            f"*Confidence gap >= 0.15. Audit trail written.*"
        )

    def _fmt_tiebreak(self, sorted_responses: list[AgentResponse]) -> str:
        top, second = sorted_responses[0], sorted_responses[1]
        gap = top.confidence_score - second.confidence_score
        return (
            f"**Concord** — human tiebreak required\n\n"
            f"Confidence gap {gap:.4f} is below threshold 0.15.\n\n"
            f"**{top.agent} agent** (score {top.confidence_score:.4f})\n"
            f"Root cause: {top.root_cause}\n"
            f"Fix: {top.suggested_fix}\n\n"
            f"**{second.agent} agent** (score {second.confidence_score:.4f})\n"
            f"Root cause: {second.root_cause}\n"
            f"Fix: {second.suggested_fix}\n\n"
            f"Reply `/approve {top.agent}` or `/approve {second.agent}` to resolve."
        )

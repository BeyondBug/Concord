"""
core/orchestrator/orchestrator.py
Main orchestrator — triage → agents → arbitration → LLM → store.
"""
import asyncio
import logging
import os
from datetime import UTC, datetime

from core.arbitration.resolver import CONFIDENCE_GAP_THRESHOLD, arbitrate
from core.mcp_runtime.audit import AuditEntry, AuditLog
from core.models.agent_response import AgentResponse, compute_confidence
from core.models.finding import Finding
from core.persistence import AuditRecord, FindingRecord, get_store
from core.triage.gate import TriageGate
from core.triage.rules.dedup import DedupRule
from core.triage.rules.patterns import KnownPatternRule
from core.triage.rules.severity import LowSeverityRule

logger = logging.getLogger("concord.orchestrator")

# Hard ceiling for one agent, on top of each connector's own HTTP timeout, so a
# hung backend can never stall a scan indefinitely.
AGENT_TIMEOUT_SECONDS = float(os.getenv("CONCORD_AGENT_TIMEOUT", "300"))


def default_agents() -> list:
    """Every domain agent, in a stable order. Imported lazily (agents import core)."""
    from agents.cicd.agent import CICDAgent
    from agents.infra.agent import InfraAgent
    from agents.kubernetes.agent import KubernetesAgent
    from agents.observability.agent import ObservabilityAgent
    from agents.security.agent import SecurityPolicyAgent
    return [InfraAgent(), CICDAgent(), SecurityPolicyAgent(),
            KubernetesAgent(), ObservabilityAgent()]


class Orchestrator:
    def __init__(self, agents: list | None = None):
        self.triage = TriageGate(rules=[
            LowSeverityRule(),
            KnownPatternRule(known_ids=set()),
            DedupRule(),
        ])
        self.audit = AuditLog()
        self._agents = agents

    @property
    def agents(self) -> list:
        if self._agents is None:
            self._agents = default_agents()
        return self._agents

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
            self._audit(finding_id=finding.id, path="fast_path",
                        reason=reason, agent=None)
            return result

        logger.info("[TRIAGE]  ESCALATE — %s", reason)

        # ── Step 2: Agents ────────────────────────────────────────
        responses, skipped = await self._run_agents(finding)
        if not responses:
            result = {"path": "ai_path", "error": "no agent responses",
                      "skipped_agents": skipped, "pr_comment": None,
                      "auto_resolved": None}
            self._store(finding, result)
            self._audit(finding_id=finding.id, path="ai_path",
                        reason="no_agent_responses", agent=None)
            return result

        # ── Step 3: Arbitrate ─────────────────────────────────────
        winner, auto_resolved = arbitrate(responses)
        sorted_r = sorted(responses, key=lambda r: r.confidence_score, reverse=True)
        scores = " | ".join(f"{r.agent}={r.confidence_score:.4f}" for r in sorted_r)
        logger.info("[ARBITRATION]  %s", scores)
        gap = (sorted_r[0].confidence_score - sorted_r[1].confidence_score
               if len(sorted_r) > 1 else 1.0)
        if auto_resolved:
            logger.info("[ARBITRATION]  AUTO-RESOLVED  %s wins (gap=%.4f)",
                        winner.agent, gap)
        else:
            logger.info("[ARBITRATION]  HUMAN TIEBREAK  gap=%.4f < %.2f",
                        gap, CONFIDENCE_GAP_THRESHOLD)

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
            "needs_approval": not auto_resolved,
            "gap": round(gap, 4),
            "pr_comment": pr_comment,
            # Candidate scores: the approval endpoint only accepts these agents.
            "agents": {r.agent: r.confidence_score for r in sorted_r},
            "analyses": {r.agent: _analysis(r) for r in sorted_r},
            "skipped_agents": skipped,
        }
        self._store(finding, result)
        self._audit(
            finding_id=finding.id, path="ai_path",
            reason="auto_resolved" if auto_resolved else "human_tiebreak",
            agent=winner.agent,
        )
        logger.info("[OUTPUT]  %s", "auto-resolved" if auto_resolved else "human tiebreak")
        return result

    # ── Helpers ───────────────────────────────────────────────────

    async def _run_agents(self, finding: Finding
                          ) -> tuple[list[AgentResponse], dict[str, str]]:
        """Run every available agent concurrently.

        Returns (responses, skipped) where skipped maps domain -> reason. An
        unavailable, unimplemented, slow or failing agent is skipped with its
        reason recorded; it never takes the whole pipeline down.
        """
        async def run_one(agent):
            domain = agent.domain
            status_fn = getattr(agent, "status", None)
            if status_fn is not None:
                status = await status_fn(fresh=True)   # act on current state
                if not status.active:
                    logger.warning("[%s]  skipped — %s", domain.upper(), status.detail)
                    return domain, None, f"blocked: {status.detail}"
            try:
                resp = await asyncio.wait_for(agent.analyze(finding),
                                              AGENT_TIMEOUT_SECONDS)
            except NotImplementedError:
                logger.warning("[%s]  not implemented yet", domain.upper())
                return domain, None, "not implemented"
            except TimeoutError:
                logger.error("[%s]  timed out after %.0fs", domain.upper(),
                             AGENT_TIMEOUT_SECONDS)
                return domain, None, f"timed out after {AGENT_TIMEOUT_SECONDS:.0f}s"
            except Exception as exc:  # noqa: BLE001 - one agent must not sink the scan
                logger.error("[%s]  error: %s", domain.upper(), exc)
                return domain, None, f"error: {exc}"[:300]
            # Deterministic confidence — never the agent's or an LLM's opinion.
            resp.confidence_score = compute_confidence(domain, finding.severity)
            logger.info("[%s]  confidence=%.4f  %s", domain.upper(),
                        resp.confidence_score, (resp.root_cause or "")[:55])
            return domain, resp, None

        outcomes = await asyncio.gather(*(run_one(a) for a in self.agents))
        responses = [resp for _, resp, _ in outcomes if resp is not None]
        skipped = {domain: why for domain, resp, why in outcomes if resp is None}
        return responses, skipped

    async def _build_pr_comment(self, finding: Finding,
                                sorted_r: list[AgentResponse],
                                auto_resolved: bool,
                                winner: AgentResponse) -> str:
        """Use the LLM for the winner's wording when configured."""
        provider = os.getenv("LLM_PROVIDER", "ollama")
        use_llm = provider in ("openai", "nvidia_nim") or (
            provider == "ollama" and os.getenv("OLLAMA_BASE_URL")
        )

        if use_llm:
            try:
                from core.orchestrator.context import sanitize_tool_output
                from core.orchestrator.llm import LLMBackend
                llm = LLMBackend()
                analysis = await llm.generate_analysis(
                    finding_id=finding.id,
                    severity=finding.severity,
                    artifact=finding.artifact,
                    title=sanitize_tool_output(finding.title, max_len=200),
                    description=sanitize_tool_output(finding.description),
                )
                if analysis.get("root_cause"):
                    winner.root_cause = analysis["root_cause"]
                    winner.suggested_fix = analysis["suggested_fix"]
                    winner.metadata["llm_provider"] = provider
                    logger.info("[LLM]  %s analysis generated", provider)
            except Exception as exc:  # noqa: BLE001 - LLM wording is optional
                logger.warning("[LLM]  failed, keeping scanner analysis: %s", exc)

        if auto_resolved:
            return (
                f"**Concord** — auto-resolved\n\n"
                f"**Agent:** {winner.agent}  |  "
                f"**Confidence:** {winner.confidence_score:.4f}\n\n"
                f"**Root cause:** {winner.root_cause}\n\n"
                f"**Suggested fix:**\n{winner.suggested_fix}\n\n"
                f"*Confidence gap ≥ {CONFIDENCE_GAP_THRESHOLD}. Audit trail written.*"
            )
        top, second = sorted_r[0], sorted_r[1]
        gap = top.confidence_score - second.confidence_score
        return (
            f"**Concord** — human tiebreak required\n\n"
            f"Confidence gap **{gap:.4f}** is below threshold "
            f"{CONFIDENCE_GAP_THRESHOLD}.\n\n"
            f"**{top.agent} agent** (score {top.confidence_score:.4f})\n"
            f"Root cause: {top.root_cause}\n"
            f"Fix: {top.suggested_fix}\n\n"
            f"**{second.agent} agent** (score {second.confidence_score:.4f})\n"
            f"Root cause: {second.root_cause}\n"
            f"Fix: {second.suggested_fix}\n\n"
            f"Reply `/approve {top.agent}` or `/approve {second.agent}` to resolve."
        )

    def _store(self, finding: Finding, result: dict) -> None:
        """Persist the finding decision. Failures are logged, never swallowed.

        A fast-path re-observation of a finding that is already stored (for
        example the dedup rule firing on a repeated scan) adds no new row: the
        stored decision — possibly a pending human tiebreak — stays current,
        and the re-observation is still written to the audit log.
        """
        try:
            store = get_store()
            if result["path"] == "fast_path" and store.get_finding(finding.id):
                result["duplicate_of_existing"] = True
                logger.info("[STORE]  %s already stored; audit-only re-observation",
                            finding.id)
                return
            store.add_finding(FindingRecord(
                id=finding.id,
                severity=finding.severity,
                artifact=finding.artifact,
                repo=finding.repository,
                source=finding.source,
                path=result["path"],
                agent=result.get("agent"),
                result=result,
            ))
        except Exception:  # noqa: BLE001 - storage must not crash processing
            logger.exception("[STORE]  failed to persist finding %s", finding.id)

    def _audit(self, finding_id: str, path: str,
               reason: str, agent: str | None) -> None:
        """Write the audit trail to both the logger and durable storage.

        Every decision — including fast-path — must be auditable, so a storage
        failure is logged loudly rather than silently dropped.
        """
        self.audit.record(AuditEntry(
            finding_id=finding_id, path=path, reason=reason,
            agent=agent, timestamp=datetime.now(UTC),
        ))
        try:
            get_store().add_audit(AuditRecord(
                finding_id=finding_id, path=path, reason=reason, agent=agent,
            ))
        except Exception:  # noqa: BLE001 - audit log must not crash processing
            logger.exception("[AUDIT]  failed to persist audit for %s", finding_id)


def _analysis(resp: AgentResponse) -> dict:
    """The per-agent evidence kept with a decision (shown in the detail view)."""
    meta = resp.metadata or {}
    keep = ("scanner", "backend", "target", "violations", "by_severity", "checks",
            "agent_ref", "endpoint", "answer", "real_scan", "real_analysis",
            "llm_provider")
    return {
        "score": resp.confidence_score,
        "root_cause": resp.root_cause,
        "suggested_fix": resp.suggested_fix,
        **{k: meta[k] for k in keep if k in meta},
    }

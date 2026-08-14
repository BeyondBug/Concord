"""
api/routes/scan.py
Triggers a real CRMS scan and handles PR approval workflow.
"""
import logging
import os
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException

router = APIRouter(prefix="/events", tags=["scan"])
logger = logging.getLogger("concord.scan")

# In-memory scan state (Phase 1: replace with Redis/DB)
_scan_state: dict = {"status": "idle", "last_scan": None, "error": None}


@router.post("/scan-crms")
async def scan_crms_endpoint(background_tasks: BackgroundTasks):
    """Trigger a real scan of crms-devops/crms in the background."""
    if _scan_state.get("status") == "scanning":
        return {"status": "already_scanning", "message": "Scan in progress"}
    _scan_state["status"]   = "scanning"
    _scan_state["started"]  = datetime.utcnow().isoformat()
    _scan_state["error"]    = None
    background_tasks.add_task(_run_scan)
    return {"status": "scanning", "message": "CRMS scan started"}


@router.get("/scan-status")
async def scan_status():
    """Return current scan status."""
    return _scan_state


@router.post("/findings/{finding_id}/approve/{agent}")
async def approve_finding(finding_id: str, agent: str):
    """
    Approve a finding (resolve the human tiebreak).
    Creates a GitHub issue on crms-devops/crms if GITHUB_TOKEN is set.
    """
    from api.routes.findings import store
    f = store.get(finding_id)
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")

    result = f.get("result", {})
    pr_comment = result.get("pr_comment", "")

    # Mark as resolved in store
    result["approved_by"]   = agent
    result["approved_at"]   = datetime.utcnow().isoformat()
    result["auto_resolved"] = True   # now resolved by human

    github_url = None
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        try:
            from core.github_utils import create_issue
            issue = create_issue(
                repo="crms-devops/crms",
                title=f"[Concord Approved] {f.get('severity','')} — {finding_id}",
                body=(f"## Concord Security Finding — Approved by human\n\n"
                      f"**Approved agent:** {agent}\n"
                      f"**Finding ID:** `{finding_id}`\n"
                      f"**Severity:** {f.get('severity','')}\n\n"
                      f"---\n\n{pr_comment}\n\n"
                      f"*Approved via Concord dashboard by human reviewer*"),
                labels=["security", "concord", "approved"],
            )
            if issue:
                github_url = issue.get("html_url")
        except Exception as exc:
            logger.error("GitHub issue failed: %s", exc)

    return {
        "status":      "approved",
        "finding_id":  finding_id,
        "agent":       agent,
        "github_url":  github_url,
        "message":     (f"GitHub issue created: {github_url}"
                        if github_url else
                        "Approved (set GITHUB_TOKEN in .env to create GitHub issue)"),
    }


async def _run_scan():
    """Background task: clone/pull CRMS, scan, save to findings store."""
    import subprocess
    from pathlib import Path

    from api.routes.findings import store
    from core.arbitration.resolver import arbitrate
    from core.models.agent_response import AgentResponse, compute_confidence
    from core.models.finding import Finding as ConcordFinding
    from core.scanner import KubernetesScanner, TerraformScanner, scan_to_dict
    from core.triage.gate import TriageGate
    from core.triage.rules.severity import LowSeverityRule

    crmss_local = Path("repos/crms")
    crms_repo  = "https://github.com/crms-devops/crms.git"
    crms_gh    = "crms-devops/crms"

    try:
        # Step 1: Clone or pull CRMS
        if crmss_local.exists() and (crmss_local / ".git").exists():
            subprocess.run(["git", "-C", str(crmss_local), "pull", "--quiet"],
                           capture_output=True)
        else:
            crmss_local.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--depth", "1", crms_repo, str(crmss_local)],
                capture_output=True)

        _scan_state["message"] = "Cloned CRMS — scanning..."

        # Step 2: Scan
        infra_dir = crmss_local / "infra"
        k8s_dir   = crmss_local / "k8s"

        tf_results  = TerraformScanner().scan(str(infra_dir) if infra_dir.exists() else str(crmss_local))
        k8s_results = KubernetesScanner().scan(str(k8s_dir)  if k8s_dir.exists()  else str(crmss_local))

        infra = scan_to_dict(tf_results,  str(infra_dir))
        cicd  = scan_to_dict(k8s_results, str(k8s_dir))

        total = infra["total"] + cicd["total"]
        sev   = ("CRITICAL" if total > 10 else
                 "HIGH"     if total > 3  else
                 "MEDIUM"   if total > 0  else "LOW")
        fid   = f"CRMS-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

        _scan_state["message"] = f"Scanned — {total} violations found"

        finding = ConcordFinding(
            id=fid, source="concord-scanner",
            artifact=str(crmss_local), severity=sev,
            title=f"CRMS real scan: {total} violation(s)",
            description=f"Real scan of {crms_gh}",
            raw={"infra": infra["total"], "cicd": cicd["total"]},
            repository=crms_gh,
        )

        gate = TriageGate(rules=[LowSeverityRule()])
        needs_ai, reason = gate.evaluate(finding)

        if not needs_ai or total == 0:
            store.add(fid, sev, str(crmss_local), crms_gh, "concord-scanner",
                      "fast_path",
                      {"path": "fast_path", "reason": reason,
                       "pr_comment": None,
                       "infra_violations": infra["total"],
                       "cicd_violations": cicd["total"]})
            _scan_state.update({"status": "done", "finding_id": fid,
                                 "total": total, "severity": sev})
            return

        responses = []
        for domain, scan in [("infra", infra), ("cicd", cicd)]:
            resp = AgentResponse(
                agent=domain, finding_id=fid,
                confidence_score=compute_confidence(domain, sev),
                root_cause=scan["root_cause"],
                suggested_fix=scan["fix"],
                metadata={"violations": scan["total"], "real": True},
            )
            responses.append(resp)

        winner, auto = arbitrate(responses)
        sr  = sorted(responses, key=lambda x: x.confidence_score, reverse=True)
        gap = sr[0].confidence_score - sr[1].confidence_score

        if auto:
            pr = (f"**Concord** — {crms_gh} scan auto-resolved\n\n"
                  f"**Agent:** {winner.agent}  **Confidence:** {winner.confidence_score:.4f}\n\n"
                  f"**Real findings from CRMS:**\n{winner.root_cause}\n\n"
                  f"**Fix:**\n{winner.suggested_fix}\n\n"
                  f"*{infra['total']} Terraform + {cicd['total']} K8s violations*")
        else:
            t, s = sr[0], sr[1]
            pr = (f"**Concord** — {crms_gh} scan: human tiebreak required\n\n"
                  f"Confidence gap **{gap:.4f}** < 0.15\n\n"
                  f"**{t.agent} agent** (score {t.confidence_score:.4f})\n"
                  f"{t.root_cause}\n\n**Fix:** {t.suggested_fix}\n\n"
                  f"**{s.agent} agent** (score {s.confidence_score:.4f})\n"
                  f"{s.root_cause}\n\n**Fix:** {s.suggested_fix}\n\n"
                  f"Use the Approve buttons in the Concord dashboard to resolve.\n"
                  f"*Real scan of {crms_gh}: {infra['total']} Terraform + {cicd['total']} K8s violations*")

        store.add(fid, sev, str(crmss_local), crms_gh, "concord-scanner", "ai_path",
                  {"path": "ai_path", "agent": winner.agent,
                   "score": winner.confidence_score,
                   "auto_resolved": auto, "pr_comment": pr,
                   "infra_violations": infra["total"],
                   "cicd_violations":  cicd["total"],
                   "infra_root_cause": infra["root_cause"],
                   "cicd_root_cause":  cicd["root_cause"],
                   "needs_approval": not auto,
                   "agents": {t.agent: t.confidence_score,
                               s.agent: s.confidence_score}})

        _scan_state.update({"status": "done", "finding_id": fid,
                             "total": total, "severity": sev,
                             "auto_resolved": auto,
                             "needs_approval": not auto})

    except Exception as exc:
        logger.error("Scan failed: %s", exc)
        _scan_state["status"] = "error"
        _scan_state["error"]  = str(exc)

"""
api/routes/events.py
Webhook receiver + /demo endpoint + approval lifecycle endpoints.
"""
import hashlib
import hmac
import logging
import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from core.models.finding import Finding
from core.persistence.store import AuditRecord, get_store

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


@router.get("/approvals/pending")
async def list_pending_approvals(limit: int = 20):
    """List findings awaiting a human approval decision."""
    store = get_store()
    pending = store.list_pending_approvals(limit=limit)
    return {"pending": pending, "total": len(pending)}


@router.post("/findings/{finding_id}/approve/{agent}")
async def approve_finding(finding_id: str, agent: str):
    """Approve a finding's tiebreak by selecting the winning agent."""
    store = get_store()
    record = store.get_finding(finding_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Finding {finding_id!r} not found")

    result = record.get("result", {})

    # Validate agent is one of the candidates that actually ran
    candidate_agents = result.get("agents", {})
    if candidate_agents and agent not in candidate_agents:
        raise HTTPException(
            status_code=400,
            detail=f"Agent {agent!r} is not a candidate for finding {finding_id!r}. "
                   f"Valid agents: {list(candidate_agents.keys())}",
        )

    result["approved_by"] = agent
    result["auto_resolved"] = True
    persisted = store.update_finding_result(finding_id, result)

    # Audit reason format must match: "human_approved:{agent}" (no space)
    store.add_audit(AuditRecord(
        finding_id=finding_id,
        path=record.get("path", ""),
        reason=f"human_approved:{agent}",
        agent=agent,
    ))

    github_url = result.get("github_url")
    return {
        "status": "approved",
        "finding_id": finding_id,
        "agent": agent,
        "persisted": persisted,
        **({"github_url": github_url} if github_url else {}),
    }


@router.post("/findings/{finding_id}/reject")
async def reject_finding(finding_id: str, reason: str = "rejected"):
    """Reject a finding — marks it resolved so it leaves the pending queue."""
    store = get_store()
    record = store.get_finding(finding_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Finding {finding_id!r} not found")

    result = record.get("result", {})
    result["rejected"] = True
    result["reject_reason"] = reason
    result["approved_by"] = "__rejected__"
    result["auto_resolved"] = True
    persisted = store.update_finding_result(finding_id, result)

    store.add_audit(AuditRecord(
        finding_id=finding_id,
        path=record.get("path", ""),
        reason=f"human_rejected:{reason}",
        agent=None,
    ))

    return {
        "status": "rejected",
        "finding_id": finding_id,
        "reason": reason,
        "persisted": persisted,
    }


@router.post("/approvals/expire")
async def expire_old_approvals(max_age_hours: int = 24):
    """Expire pending approvals older than max_age_hours; audits each one."""
    store = get_store()
    pending = store.list_pending_approvals(limit=500)
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    expired = []

    for record in pending:
        ts_str = record.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
        except ValueError:
            continue

        if ts < cutoff:
            finding_id = record["id"]
            result = record.get("result", {})
            result["approved_by"] = "__expired__"
            result["auto_resolved"] = True
            store.update_finding_result(finding_id, result)
            store.add_audit(AuditRecord(
                finding_id=finding_id,
                path=record.get("path", ""),
                reason=f"approval_expired:{max_age_hours}h",
                agent=None,
            ))
            expired.append(finding_id)

    return {"status": "ok", "count": len(expired), "expired": expired}

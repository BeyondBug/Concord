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

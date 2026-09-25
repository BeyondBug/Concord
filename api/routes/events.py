"""
api/routes/events.py
GitHub webhook receiver (public, HMAC-verified) and the demo trigger
(API-key protected — it runs the full pipeline and writes to the store).
"""
import hashlib
import hmac
import json
import logging
import os
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from core.models.finding import Finding

router = APIRouter(prefix="/events", tags=["events"])
demo_router = APIRouter(prefix="/events", tags=["events"])
logger = logging.getLogger("concord.events")

Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]


def _verify_signature(body: bytes, sig_header: str) -> bool:
    secret = os.getenv("WEBHOOK_SECRET", "")
    if not secret:
        return True  # dev mode: skip check if no secret configured
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return hmac.compare_digest("sha256=" + mac.hexdigest(), sig_header or "")


async def _run(finding: Finding) -> None:
    from core.orchestrator.orchestrator import Orchestrator
    try:
        await Orchestrator().process(finding)
    except Exception:  # noqa: BLE001 - background task: log, never vanish silently
        logger.exception("webhook processing failed for %s", finding.id)


@router.post("/github", status_code=202)
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Accept a GitHub push webhook and analyze it in the background."""
    body = await request.body()
    if not _verify_signature(body, request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    if request.headers.get("X-GitHub-Event", "push") == "ping":
        return {"status": "pong"}

    repo_info = payload.get("repository")
    repo = repo_info.get("full_name") if isinstance(repo_info, dict) else None
    repo = repo or "unknown/repo"
    commit = payload.get("head_commit")
    if not isinstance(commit, dict):
        commit = {}
    sha = str(commit.get("id") or "")
    if not sha:
        # Nothing to analyze (e.g. branch deletion). Say so instead of inventing
        # a placeholder finding.
        return {"status": "ignored", "reason": "no head_commit in payload", "repo": repo}

    modified = commit.get("modified") or commit.get("added") or []
    finding = Finding(
        id=f"GH-{sha[:12]}",
        source="github-webhook",
        artifact=str(modified[0]) if modified else repo,
        severity="HIGH",
        title=str(commit.get("message") or "Push event")[:80],
        description=f"Push to {repo}",
        raw=payload,
        repository=repo,
        commit_sha=sha,
    )
    background_tasks.add_task(_run, finding)
    return {"status": "received", "finding_id": finding.id, "repo": repo}


@demo_router.post("/demo")
async def demo_endpoint(severity: Severity = Query("CRITICAL")):
    """Run a sample finding through Concord synchronously.

    The finding is a fixed sample (clearly sourced ``concord-demo``); the
    agents and arbitration that process it are real.
    """
    from core.orchestrator.orchestrator import Orchestrator

    finding = Finding(
        id=f"DEMO-IAM-{severity}",
        source="concord-demo",
        artifact="tests/fixtures/terraform/main.tf",
        severity=severity,
        title="IAM policy allows overly permissive actions",
        description="AWS IAM policy grants * actions on * resources",
        raw={"demo": True, "rule_id": "TF-IAM-001"},
        repository="concord/demo",
    )
    return await Orchestrator().process(finding)

"""Webhook receiver — GitHub/GitLab push events."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/github")
async def github_webhook(request: Request):
    # TODO Phase 1: verify WEBHOOK_SECRET, send to triage gate
    payload = await request.json()
    repo = payload.get("repository", {}).get("full_name", "unknown")
    return {"status": "received", "repo": repo}

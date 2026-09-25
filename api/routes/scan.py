"""
api/routes/scan.py
Repository scan trigger and the human approval workflow.

A scan clones (or updates) the target repository into ``repos/``, derives one
finding for the checked-out commit, and sends it through the orchestrator —
the same triage → agents → arbitration → store → audit pipeline as every
other finding, so every agent that is available (including kagent / HolmesGPT
when their connectors are live) takes part.

The finding id is derived from the commit (``<PREFIX>-<sha12>``). Scanning an
unchanged commit again therefore does not create a duplicate finding: it is
recorded in the audit log as a re-scan and the existing decision stays current.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi import Path as PathParam
from pydantic import BaseModel

from core.models.agent_response import SOURCE_RELIABILITY
from core.persistence import AuditRecord, get_store
from core.persistence.store import _is_pending

router = APIRouter(prefix="/events", tags=["scan"])
logger = logging.getLogger("concord.scan")

_ID = PathParam(min_length=1, max_length=200)
_SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


def scan_target() -> dict[str, str]:
    """The repository the scan button scans (configurable, CRMS by default)."""
    url = os.getenv("CONCORD_SCAN_REPO_URL", "https://github.com/crms-devops/crms.git")
    name = os.getenv("CONCORD_SCAN_REPO", "crms-devops/crms")
    local = os.getenv("CONCORD_SCAN_DIR", f"repos/{name.split('/')[-1]}")
    prefix = os.getenv("CONCORD_SCAN_ID_PREFIX", name.split("/")[-1].upper())
    return {"url": url, "name": name, "local": local, "prefix": prefix}


class ScanState(BaseModel):
    status: str = "idle"             # idle | scanning | done | error
    target: str = ""
    message: str | None = None
    started: str | None = None
    finished: str | None = None
    error: str | None = None
    finding_id: str | None = None
    commit: str | None = None
    total: int | None = None
    severity: str | None = None
    by_scanner: dict[str, int] | None = None
    path: str | None = None
    auto_resolved: bool | None = None
    needs_approval: bool | None = None
    unchanged: bool | None = None
    skipped_agents: dict[str, str] | None = None
    warnings: list[str] = []


# Process-local scan state. One scan at a time; the lock closes the
# check-then-set race between two near-simultaneous trigger requests.
_scan_state = ScanState(target=scan_target()["name"])
_scan_lock = asyncio.Lock()


@router.post("/scan-crms", response_model=ScanState)
async def scan_crms_endpoint(background_tasks: BackgroundTasks) -> ScanState:
    """Trigger a scan of the configured repository in the background."""
    global _scan_state
    async with _scan_lock:
        if _scan_state.status == "scanning":
            raise HTTPException(status_code=409, detail="A scan is already running.")
        target = scan_target()
        _scan_state = ScanState(status="scanning", target=target["name"],
                                started=_now(), message="Starting scan…")
    background_tasks.add_task(_run_scan)
    return _scan_state


@router.get("/scan-status", response_model=ScanState)
async def scan_status() -> ScanState:
    """Current (or last) scan state."""
    if _scan_state.status == "idle":
        _scan_state.target = scan_target()["name"]
    return _scan_state


# ── Approval workflow ─────────────────────────────────────────────────


def _pending_or_409(finding_id: str) -> dict[str, Any]:
    f = get_store().get_finding(finding_id)
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    result = f.get("result", {})
    if f.get("path") != "ai_path" or not _is_pending(result):
        raise HTTPException(
            status_code=409,
            detail=f"Finding '{finding_id}' is not awaiting a decision "
                   f"({_resolution(result)}).")
    return f


def _resolution(result: dict[str, Any]) -> str:
    if result.get("approved_by"):
        return f"already approved: {result['approved_by']}"
    if result.get("rejected"):
        return "already rejected"
    if result.get("expired"):
        return "expired"
    if result.get("auto_resolved") is True:
        return "auto-resolved"
    return "not an AI-path tiebreak"


@router.post("/findings/{finding_id}/approve/{agent}")
async def approve_finding(finding_id: str = _ID, agent: str = PathParam(max_length=40)):
    """Resolve a human tiebreak by choosing the winning agent.

    Creates a GitHub issue on the scanned repository when GITHUB_TOKEN is set.
    """
    f = _pending_or_409(finding_id)
    result = f.get("result", {})

    # Only an agent that actually produced a candidate may win.
    candidates = result.get("agents")
    if isinstance(candidates, dict):
        if agent not in candidates:
            raise HTTPException(
                status_code=400,
                detail=f"Agent '{agent}' is not a candidate for this finding. "
                       f"Choose one of: {', '.join(sorted(candidates))}.")
    elif agent not in SOURCE_RELIABILITY:
        raise HTTPException(status_code=400, detail=f"Unknown agent '{agent}'.")

    github_url, github_error = None, None
    if os.getenv("GITHUB_TOKEN", ""):
        github_url, github_error = await asyncio.to_thread(
            _create_issue, f, agent, finding_id, result.get("pr_comment") or "")

    result.update({
        "approved_by": agent,
        "approved_at": _now(),
        "auto_resolved": True,        # now resolved — by a human
        "agent": agent,
        "needs_approval": False,
        "github_url": github_url,
    })
    persisted = get_store().update_finding_result(finding_id, result)
    get_store().add_audit(AuditRecord(
        finding_id=finding_id, path="ai_path",
        reason=f"human_approved:{agent}", agent=agent,
    ))
    logger.info("[APPROVAL]  finding=%s approved agent=%s persisted=%s",
                finding_id, agent, persisted)

    if github_url:
        message = f"Approved. GitHub issue created: {github_url}"
    elif github_error:
        message = f"Approved. GitHub issue NOT created: {github_error}"
    else:
        message = "Approved. (Set GITHUB_TOKEN to also open a GitHub issue.)"
    return {"status": "approved", "finding_id": finding_id, "agent": agent,
            "persisted": persisted, "github_url": github_url,
            "github_error": github_error, "message": message}


def _create_issue(f: dict, agent: str, finding_id: str,
                  pr_comment: str) -> tuple[str | None, str | None]:
    from core.github_utils import create_issue
    repo = f.get("repo") or scan_target()["name"]
    issue = create_issue(
        repo=repo,
        title=f"[Concord Approved] {f.get('severity', '')} — {finding_id}",
        body=(f"## Concord Security Finding — Approved by human\n\n"
              f"**Approved agent:** {agent}\n"
              f"**Finding ID:** `{finding_id}`\n"
              f"**Severity:** {f.get('severity', '')}\n\n"
              f"---\n\n{pr_comment}\n\n"
              f"*Approved via Concord by a human reviewer*"),
        labels=["security", "concord", "approved"],
    )
    if issue and issue.get("html_url"):
        return issue["html_url"], None
    return None, f"GitHub API call to {repo} failed (see server log)"


@router.get("/approvals/pending")
async def list_pending_approvals(limit: int = Query(100, ge=1, le=500)):
    """AI-path findings awaiting a human decision (tiebreaks)."""
    pending = get_store().list_pending_approvals(limit=limit)
    return {"pending": pending, "total": len(pending)}


@router.post("/findings/{finding_id}/reject")
async def reject_finding(finding_id: str = _ID,
                         reason: str = Query("rejected by reviewer",
                                             min_length=1, max_length=200)):
    """Reject a pending finding: resolved-as-rejected, durable and audited."""
    f = _pending_or_409(finding_id)
    result = f.get("result", {})
    result.update({"rejected": True, "rejected_at": _now(), "reject_reason": reason,
                   "auto_resolved": True, "needs_approval": False})
    persisted = get_store().update_finding_result(finding_id, result)
    get_store().add_audit(AuditRecord(
        finding_id=finding_id, path="ai_path",
        reason=f"human_rejected:{reason}"[:200], agent=None,
    ))
    logger.info("[APPROVAL]  finding=%s REJECTED persisted=%s", finding_id, persisted)
    return {"status": "rejected", "finding_id": finding_id,
            "persisted": persisted, "reason": reason}


@router.post("/approvals/expire")
async def expire_stale_approvals(max_age_hours: float = Query(24.0, gt=0, le=24 * 365)):
    """Expire pending approvals older than ``max_age_hours`` (each one audited).

    A fail-safe so stale human-in-the-loop items cannot block forever. Meant
    for a scheduler; also usable manually.
    """
    store_ = get_store()
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    expired = []
    for f in store_.list_pending_approvals(limit=500):
        try:
            created = datetime.fromisoformat(f.get("timestamp", ""))
        except ValueError:
            logger.warning("[APPROVAL]  %s has an unparseable timestamp", f["id"])
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if created >= cutoff:
            continue
        result = f.get("result", {})
        result.update({"expired": True, "expired_at": _now(),
                       "auto_resolved": True, "needs_approval": False})
        store_.update_finding_result(f["id"], result)
        store_.add_audit(AuditRecord(
            finding_id=f["id"], path="ai_path",
            reason=f"approval_expired:age>{max_age_hours}h", agent=None,
        ))
        expired.append(f["id"])

    logger.info("[APPROVAL]  expired %d stale approval(s)", len(expired))
    return {"status": "ok", "expired": expired, "count": len(expired)}


# ── Scan pipeline ─────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=300)


def checkout(url: str, local: Path) -> tuple[str, list[str]]:
    """Clone or fast-forward ``local``; return (commit or content hash, warnings).

    A failed pull on an existing checkout is a warning (scan the cached copy);
    a failed clone with no usable copy is an error.
    """
    warnings: list[str] = []
    if (local / ".git").exists():
        pull = _git("pull", "--ff-only", "--quiet", cwd=str(local))
        if pull.returncode != 0:
            warnings.append("git pull failed; scanned the cached checkout "
                            f"({pull.stderr.strip()[:160]})")
    elif local.exists() and any(local.iterdir()):
        warnings.append(f"{local} is not a git checkout; scanned it as-is")
    else:
        local.parent.mkdir(parents=True, exist_ok=True)
        clone = _git("clone", "--depth", "1", url, str(local))
        if clone.returncode != 0:
            raise RuntimeError(f"git clone {url} failed: {clone.stderr.strip()[:300]}")

    if (local / ".git").exists():
        head = _git("rev-parse", "HEAD", cwd=str(local))
        if head.returncode == 0:
            return head.stdout.strip(), warnings
    return _content_hash(local), warnings


def _content_hash(root: Path) -> str:
    """Stable hash of a non-git tree, so re-scans still map to one finding id."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def prescan(local: Path) -> dict[str, Any]:
    """Count violations per scanner to set the finding's severity.

    Severity is the highest severity any scanner reported (LOW when clean), so
    a clean repository takes the fast path and a single CRITICAL escalates.
    """
    from core.scanner import KubernetesScanner, SourceCodeScanner, TerraformScanner

    by_scanner, worst = {}, "LOW"
    for name, scanner in (("terraform", TerraformScanner()),
                          ("kubernetes", KubernetesScanner()),
                          ("source", SourceCodeScanner())):
        found = scanner.scan(str(local))
        by_scanner[name] = len(found)
        for v in found:
            if _SEV_RANK.get(v.severity, 0) > _SEV_RANK[worst]:
                worst = v.severity
    return {"by_scanner": by_scanner, "total": sum(by_scanner.values()),
            "severity": worst}


async def _run_scan() -> None:
    """Background task: checkout → pre-scan → orchestrator → state."""
    from core.models.finding import Finding
    from core.orchestrator.orchestrator import Orchestrator

    state, target = _scan_state, scan_target()
    local = Path(target["local"])
    try:
        state.message = f"Fetching {target['name']}…"
        commit, warnings = await asyncio.to_thread(checkout, target["url"], local)
        state.commit, state.warnings = commit, warnings

        fid = f"{target['prefix']}-{commit[:12]}"
        state.finding_id = fid
        existing = get_store().get_finding(fid)
        if existing:
            get_store().add_audit(AuditRecord(
                finding_id=fid, path=existing.get("path", "fast_path"),
                reason=f"rescan_unchanged:{commit[:12]}", agent=None))
            res = existing.get("result", {})
            state.status, state.unchanged = "done", True
            state.severity, state.path = existing.get("severity"), existing.get("path")
            state.total = res.get("scan", {}).get("total")
            state.by_scanner = res.get("scan", {}).get("by_scanner")
            state.auto_resolved = res.get("auto_resolved")
            state.needs_approval = _is_pending(res)
            state.message = f"Commit {commit[:12]} already analyzed; no new finding."
            state.finished = _now()
            return

        state.message = "Scanning…"
        pre = await asyncio.to_thread(prescan, local)
        finding = Finding(
            id=fid, source="concord-scanner", artifact=str(local),
            severity=pre["severity"],
            title=f"{target['name']} scan: {pre['total']} violation(s)",
            description=(f"Scan of {target['name']} at {commit[:12]}: "
                         + ", ".join(f"{k} {v}" for k, v in pre["by_scanner"].items())),
            raw={"scan": pre, "commit": commit},
            repository=target["name"], commit_sha=commit,
        )
        state.message = "Running agents…"
        result = await Orchestrator().process(finding)

        # Keep the scan summary with the stored decision (for the detail view).
        result["scan"] = {**pre, "commit": commit, "warnings": warnings}
        get_store().update_finding_result(fid, result)

        state.status = "done"
        state.total, state.severity = pre["total"], pre["severity"]
        state.by_scanner, state.path = pre["by_scanner"], result.get("path")
        state.auto_resolved = result.get("auto_resolved")
        state.needs_approval = bool(result.get("needs_approval"))
        state.skipped_agents = result.get("skipped_agents") or {}
        state.message = f"Scanned {commit[:12]}: {pre['total']} violation(s)"
        state.finished = _now()
    except Exception as exc:  # noqa: BLE001 - reported to the UI, never swallowed
        logger.exception("Scan failed")
        state.status, state.error = "error", str(exc)[:500]
        state.message, state.finished = "Scan failed", _now()

#!/usr/bin/env python3
"""
Concord CLI — command-line interface for the Concord API.

Usage (from repo root):
    python concord_cli/main.py [COMMAND] [OPTIONS]
    python concord_cli/main.py --help

Machine-readable output: pass --json to any data command (or set
CONCORD_OUTPUT=json) to get pure JSON on stdout with no terminal decoration,
so the CLI is safe to pipe. Colour is disabled automatically when stdout is
not a TTY or when NO_COLOR is set.

Exit codes: 0 success · 1 the API refused the request (auth, validation,
not found, conflict — its reason is printed) · 2 the API is unreachable.
"""
import json as _json
import os
import sys
import time
import webbrowser

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = typer.Typer(
    name="concord",
    help="Concord — AI DevSecOps Orchestration Platform  |  github.com/BeyondBug/Concord",
    add_completion=True,
    rich_markup_mode="rich",
)

# Colour off when piped or NO_COLOR set; keeps machine output clean.
_NO_COLOR = bool(os.getenv("NO_COLOR")) or not sys.stdout.isatty()
con = Console(no_color=_NO_COLOR)
err = Console(stderr=True, no_color=_NO_COLOR)

API = os.getenv("CONCORD_API_URL", "http://localhost:8000")
API_KEY = os.getenv("CONCORD_API_KEY", "")

SEV_COLOR = {
    "CRITICAL": "red", "HIGH": "orange3",
    "MEDIUM": "yellow", "LOW": "green",
}

# ── Shared helpers ────────────────────────────────────────────────────


def _want_json(flag: bool) -> bool:
    return flag or os.getenv("CONCORD_OUTPUT", "").lower() == "json"


def _headers() -> dict:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def _api_get(path: str, params: dict | None = None) -> dict:
    with httpx.Client(timeout=15) as client:
        r = client.get(f"{API}{path}", params=params, headers=_headers())
        r.raise_for_status()
        return r.json()


def _api_post(path: str, params: dict | None = None, timeout: float = 30) -> dict:
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{API}{path}", params=params, headers=_headers())
        r.raise_for_status()
        return r.json()


def _call(fn, *args, **kwargs) -> dict:
    """Run an API call; turn failures into a clear message and exit code."""
    try:
        return fn(*args, **kwargs)
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        try:
            detail = e.response.json().get("detail", "")
        except Exception:  # noqa: BLE001 - non-JSON error body
            detail = e.response.text[:200]
        if isinstance(detail, list):  # FastAPI validation errors
            detail = "; ".join(f"{'.'.join(map(str, d.get('loc', [])))}: {d.get('msg')}"
                               for d in detail)
        if code == 401:
            detail = f"{detail} Set CONCORD_API_KEY to the server's key."
        err.print(f"[red]Request failed ({code}):[/red] {escape(str(detail))}",
                  soft_wrap=True)
        raise typer.Exit(1) from None
    except httpx.HTTPError as e:
        _die_unreachable(e)


def _die_unreachable(exc: Exception) -> None:
    err.print(f"[red]Cannot reach API ({API}): {escape(str(exc))}[/red]", soft_wrap=True)
    err.print("  Start it with: [bold]uvicorn api.main:app --reload[/bold]")
    raise typer.Exit(2)


def _emit_json(obj) -> None:
    con.print_json(_json.dumps(obj))


def _sev(sev: str) -> str:
    c = SEV_COLOR.get(sev, "white")
    return f"[{c}]{escape(sev or '?')}[/{c}]"


# ── Commands ──────────────────────────────────────────────────────────


@app.command()
def version():
    """Print version information."""
    con.print("[bold green]Concord[/bold green] v0.1.0")
    con.print("  AI DevSecOps Orchestration Platform")
    con.print(f"  API: {API}")


@app.command()
def health(json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """Check API health and auth posture."""
    d = _call(_api_get, "/health")
    if _want_json(json):
        _emit_json(d)
        return
    ok = d.get("status") == "ok"
    dot = "[green]● ok[/green]" if ok else "[red]● down[/red]"
    con.print(f"\n  Status     {dot}")
    con.print(f"  Version    {d.get('version','?')}")
    con.print(f"  Auth       {'enforced' if d.get('auth_enforced') else 'open (dev)'}")
    con.print()


@app.command()
def findings(
    limit: int = typer.Option(10, "--limit", "-n"),
    severity: str = typer.Option(None, "--severity", "-s",
                                 help="Filter: CRITICAL|HIGH|MEDIUM|LOW"),
    path: str = typer.Option(None, "--path", help="Filter: fast_path|ai_path"),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Show recent findings from the live API."""
    params = {"limit": limit}
    if severity:
        params["severity"] = severity.upper()
    if path:
        params["path"] = path
    d = _call(_api_get, "/findings/", params=params)

    if _want_json(json):
        _emit_json(d)
        return

    s = d.get("stats", {})
    con.print(
        f"\n  Total [bold]{s.get('total',0)}[/bold]  "
        f"Fast [green]{s.get('fast',0)}[/green]  "
        f"AI [cyan]{s.get('ai',0)}[/cyan]  "
        f"Tiebreaks [yellow]{s.get('tiebreaks',0)}[/yellow]"
    )
    lst = d.get("findings", [])
    if not lst:
        con.print("\n  [dim]No findings yet. Run: concord scan  (or concord invoke)[/dim]")
        return

    t = Table(show_header=True, header_style="bold", show_lines=False)
    for col in ("ID", "Severity", "Path", "Agent", "Status", "Artifact", "When (UTC)"):
        t.add_column(col)
    for f in lst:
        p = f.get("path", "")
        path_str = f"[cyan]{p}[/cyan]" if p == "ai_path" else f"[dim]{p}[/dim]"
        t.add_row(
            escape(f.get("id", "")), _sev(f.get("severity", "")), path_str,
            escape(f.get("agent") or "—"), _status(f),
            escape((f.get("artifact", "") or "").replace("\\", "/").split("/")[-1]),
            (f.get("timestamp", "") or "")[:16].replace("T", " "),
        )
    con.print(t)


def _status(f: dict) -> str:
    r = f.get("result", {}) or {}
    if r.get("approved_by"):
        return f"[green]approved:{escape(r['approved_by'])}[/green]"
    if r.get("rejected"):
        return "[red]rejected[/red]"
    if r.get("expired"):
        return "[dim]expired[/dim]"
    if r.get("auto_resolved") is False:
        return "[yellow]needs approval[/yellow]"
    if r.get("auto_resolved") is True:
        return "[green]auto-resolved[/green]"
    if r.get("error"):
        return "[red]no agents[/red]"
    return "[dim]fast path[/dim]"


@app.command()
def finding(
    finding_id: str = typer.Argument(..., help="Finding ID."),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Show one finding: per-agent analysis, resolution and audit timeline."""
    d = _call(_api_get, f"/findings/{finding_id}/detail")
    if _want_json(json):
        _emit_json(d)
        return
    f, r = d["finding"], d["finding"].get("result", {}) or {}
    con.print(f"\n  [bold]{escape(f['id'])}[/bold]  {_sev(f.get('severity', ''))}  "
              f"{_status(f)}")
    con.print(f"  Repo {escape(f.get('repo') or '—')}  ·  Artifact "
              f"{escape(f.get('artifact') or '—')}  ·  Path {f.get('path')}")
    for agent, a in (r.get("analyses") or {}).items():
        body = (f"[bold]Root cause[/bold]\n{escape(str(a.get('root_cause', '')))}\n\n"
                f"[bold]Fix[/bold]\n{escape(str(a.get('suggested_fix', '')))}")
        con.print(Panel(body, title=f"{agent} · confidence {a.get('score', 0):.4f}",
                        border_style="cyan"))
    for agent, why in (r.get("skipped_agents") or {}).items():
        con.print(f"  [dim]skipped {escape(agent)}: {escape(why)}[/dim]")
    if d.get("timeline"):
        t = Table(title="Audit timeline", header_style="bold")
        for col in ("When (UTC)", "Path", "Reason", "Agent", "Correlation"):
            t.add_column(col)
        for e in d["timeline"]:
            t.add_row((e.get("timestamp") or "")[:19].replace("T", " "), e.get("path", ""),
                      escape(e.get("reason", "")), escape(e.get("agent") or "—"),
                      escape(e.get("correlation_id") or "-"))
        con.print(t)


@app.command()
def audit(
    limit: int = typer.Option(20, "--limit", "-n"),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Show the audit trail (with correlation IDs)."""
    d = _call(_api_get, "/audit/", params={"limit": limit})

    if _want_json(json):
        _emit_json(d)
        return

    entries = d.get("entries", [])
    if not entries:
        con.print("\n  [dim]No audit entries yet.[/dim]")
        return
    t = Table(show_header=True, header_style="bold", show_lines=False)
    for col in ("Finding", "Path", "Reason", "Agent", "Correlation", "When (UTC)"):
        t.add_column(col)
    for e in entries:
        t.add_row(
            escape(e.get("finding_id", "")), e.get("path", ""),
            escape((e.get("reason", "") or "")[:40]), escape(e.get("agent") or "—"),
            escape((e.get("correlation_id", "-") or "-")[:16]),
            (e.get("timestamp", "") or "")[:19].replace("T", " "),
        )
    con.print(t)


@app.command()
def approvals(
    limit: int = typer.Option(20, "--limit", "-n"),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """List findings awaiting a human approval decision."""
    d = _call(_api_get, "/events/approvals/pending", params={"limit": limit})

    if _want_json(json):
        _emit_json(d)
        return

    pending = d.get("pending", [])
    if not pending:
        con.print("\n  [green]No approvals pending.[/green]")
        return
    con.print(f"\n  [yellow]{len(pending)} finding(s) awaiting approval[/yellow]")
    t = Table(show_header=True, header_style="bold", show_lines=False)
    for col in ("ID", "Severity", "Candidates", "Artifact"):
        t.add_column(col)
    for f in pending:
        agents = (f.get("result", {}) or {}).get("agents") or {}
        cands = ", ".join(f"{a} {s:.2f}" for a, s in agents.items())
        t.add_row(escape(f.get("id", "")), _sev(f.get("severity", "")),
                  escape(cands) or "—",
                  escape((f.get("artifact", "") or "").replace("\\", "/").split("/")[-1]))
    con.print(t)
    con.print("  [dim]Resolve: concord approve <ID> <agent>  ·  concord reject <ID>[/dim]")


@app.command()
def approve(
    finding_id: str = typer.Argument(..., help="Finding ID to approve."),
    agent: str = typer.Argument(..., help="Winning agent to approve."),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Approve a finding's tiebreak by selecting the winning agent."""
    d = _call(_api_post, f"/events/findings/{finding_id}/approve/{agent}")
    if _want_json(json):
        _emit_json(d)
        return
    con.print(f"\n  [green]✓ Approved[/green] {escape(finding_id)} → agent "
              f"[bold]{escape(agent)}[/bold]")
    if d.get("persisted"):
        con.print("  [dim]Resolution persisted and audited.[/dim]")
    if d.get("github_url"):
        con.print(f"  Issue: {d['github_url']}")
    elif d.get("github_error"):
        con.print(f"  [yellow]{escape(d['github_error'])}[/yellow]")


@app.command()
def reject(
    finding_id: str = typer.Argument(..., help="Finding ID to reject."),
    reason: str = typer.Option("rejected by reviewer", "--reason", "-r"),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Reject a pending finding (records a durable, audited decision)."""
    d = _call(_api_post, f"/events/findings/{finding_id}/reject",
              params={"reason": reason})
    if _want_json(json):
        _emit_json(d)
        return
    con.print(f"\n  [red]✕ Rejected[/red] {escape(finding_id)}  [dim]({escape(reason)})[/dim]")


@app.command()
def scan(
    wait: bool = typer.Option(True, "--wait/--no-wait",
                              help="Wait for the scan to finish."),
    timeout: int = typer.Option(900, "--timeout", help="Seconds to wait."),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Scan the configured repository (default crms-devops/crms)."""
    d = _call(_api_post, "/events/scan-crms")
    if wait:
        deadline = time.monotonic() + timeout
        last = None
        while d.get("status") == "scanning":
            if time.monotonic() > deadline:
                err.print(f"[yellow]Still scanning after {timeout}s; "
                          "check: concord scan-status[/yellow]")
                raise typer.Exit(1)
            if not _want_json(json) and d.get("message") != last:
                last = d.get("message")
                err.print(f"  [dim]{escape(last or 'scanning…')}[/dim]")
            time.sleep(2)
            d = _call(_api_get, "/events/scan-status")
    if _want_json(json):
        _emit_json(d)
    else:
        _print_scan(d)
    if d.get("status") == "error":
        raise typer.Exit(1)


@app.command("scan-status")
def scan_status(json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """Show the current or last scan."""
    d = _call(_api_get, "/events/scan-status")
    if _want_json(json):
        _emit_json(d)
        return
    _print_scan(d)


def _print_scan(d: dict) -> None:
    st = d.get("status")
    con.print(f"\n  Target   {escape(d.get('target') or '—')}")
    if st == "idle":
        con.print("  Status   [dim]no scan has run in this server process[/dim]\n")
        return
    color = {"done": "green", "error": "red", "scanning": "yellow"}.get(st, "white")
    con.print(f"  Status   [{color}]{st}[/{color}]  {escape(d.get('message') or '')}")
    if d.get("error"):
        con.print(f"  Error    [red]{escape(d['error'])}[/red]")
    if d.get("finding_id"):
        con.print(f"  Finding  {escape(d['finding_id'])}  (commit "
                  f"{(d.get('commit') or '')[:12]})")
    if d.get("total") is not None:
        parts = ", ".join(f"{k} {v}" for k, v in (d.get("by_scanner") or {}).items())
        con.print(f"  Result   {d['total']} violation(s), {_sev(d.get('severity') or '')}"
                  f"  [dim]{escape(parts)}[/dim]")
    if d.get("needs_approval"):
        con.print("  [yellow]Needs a human decision:[/yellow] concord approvals")
    for agent, why in (d.get("skipped_agents") or {}).items():
        con.print(f"  [dim]skipped {escape(agent)}: {escape(why)}[/dim]")
    for w in d.get("warnings") or []:
        con.print(f"  [yellow]warning:[/yellow] {escape(w)}")
    con.print()


@app.command()
def stats(json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """One-line summary: findings, pending approvals, audit events."""
    f = _call(_api_get, "/findings/")
    p = _call(_api_get, "/events/approvals/pending")
    a = _call(_api_get, "/audit/", params={"limit": 1000})
    s = f.get("stats", {})
    summary = {
        "total": s.get("total", 0),
        "fast": s.get("fast", 0),
        "ai": s.get("ai", 0),
        "tiebreaks": s.get("tiebreaks", 0),
        "pending_approvals": p.get("total", 0),
        "audit_events": a.get("total", 0),
    }
    if _want_json(json):
        _emit_json(summary)
        return
    con.print(
        f"\n  Findings [bold]{summary['total']}[/bold]  "
        f"(fast [green]{summary['fast']}[/green] · ai [cyan]{summary['ai']}[/cyan])   "
        f"Pending [yellow]{summary['pending_approvals']}[/yellow]   "
        f"Audit [dim]{summary['audit_events']}[/dim]\n"
    )


@app.command()
def diagnostics(json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """Run environment + API connectivity checks and report status."""
    checks = []   # (name, ok, detail, counts_toward_health)

    api_ok = False
    health_d: dict = {}
    try:
        health_d = _api_get("/health")
        api_ok = health_d.get("status") == "ok"
        checks.append(("API reachable", api_ok, API, True))
    except Exception as e:  # noqa: BLE001
        checks.append(("API reachable", False, f"{API} ({e})", True))

    if api_ok:
        enforced = bool(health_d.get("auth_enforced"))
        checks.append(("Auth enforced", enforced,
                       "enforced" if enforced else "open dev mode", False))
        try:
            ag = _api_get("/agents/")
            for a in ag.get("agents", []):
                checks.append((f"Agent {a['domain']}", a.get("status") == "active",
                               a.get("detail", ""), False))
        except httpx.HTTPStatusError as e:
            checks.append(("Agents endpoint", False,
                           f"HTTP {e.response.status_code} (API key?)", True))
        except Exception as e:  # noqa: BLE001
            checks.append(("Agents endpoint", False, str(e), True))

    checks.append(("CONCORD_API_KEY set", bool(API_KEY),
                   "yes" if API_KEY else "no (dev mode)", False))
    checks.append(("CONCORD_API_URL", True, API, False))
    checks.append(("Output mode", True,
                   "json" if os.getenv("CONCORD_OUTPUT", "").lower() == "json" else "human",
                   False))

    healthy = all(ok for _name, ok, _detail, counts in checks if counts)
    if _want_json(json):
        _emit_json({"checks": [{"name": n, "ok": ok, "detail": d}
                               for n, ok, d, _ in checks],
                    "healthy": healthy})
        if not api_ok:
            raise typer.Exit(2)
        return

    con.print("\n  [bold]Concord diagnostics[/bold]\n")
    for name, ok, detail, _ in checks:
        mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
        con.print(f"  {mark}  {name:<22}[dim]{escape(str(detail))}[/dim]")
    con.print()
    if not api_ok:
        con.print("  [yellow]API not reachable.[/yellow] Start it with:")
        con.print("    [bold]uvicorn api.main:app --reload[/bold]\n")
        raise typer.Exit(2)


@app.command()
def completion():
    """Show how to enable shell completion for the concord CLI."""
    con.print("\n  Enable shell completion (Typer built-in):\n")
    con.print("    [bold]python concord_cli/main.py --install-completion[/bold]")
    con.print("  then restart your shell. Supported: bash, zsh, fish, PowerShell.\n")
    con.print("  To preview the script without installing:")
    con.print("    [bold]python concord_cli/main.py --show-completion[/bold]\n")


@app.command()
def invoke(
    severity: str = typer.Option("CRITICAL", "--severity", "-s",
                                 help="CRITICAL | HIGH | MEDIUM | LOW"),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Run the demo finding through the real pipeline and show the result."""
    d = _call(_api_post, "/events/demo", params={"severity": severity.upper()},
              timeout=600)
    if _want_json(json):
        _emit_json(d)
        return
    _print_result(d)


@app.command()
def agents(json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """List domain agents: active, or blocked with the reason."""
    d = _call(_api_get, "/agents/")
    if _want_json(json):
        _emit_json(d)
        return
    t = Table(title="Domain Agents", header_style="bold green")
    for col in ("Agent", "Backing", "Reliability", "Status", "Detail"):
        t.add_column(col)
    for a in d.get("agents", []):
        status = a.get("status")
        badge = ("[green]● active[/green]" if status == "active"
                 else f"[red]○ {escape(status or 'unknown')}[/red]")
        t.add_row(escape(a.get("domain", "")), escape(a.get("backing", "")),
                  f"{a.get('reliability', 0):.2f}", badge,
                  f"[dim]{escape(a.get('detail', ''))}[/dim]")
    con.print(t)


@app.command()
def dashboard():
    """Open the Concord dashboard in your browser."""
    con.print(f"\n  Opening dashboard → [bold cyan]{API}[/bold cyan]\n")
    webbrowser.open(API)


def _print_result(result: dict):
    path = result.get("path", "unknown")
    if path == "fast_path":
        con.print(f"\n  [bold cyan]TRIAGE[/bold cyan]  FAST PATH — "
                  f"{escape(str(result.get('reason')))}")
        con.print("  [dim]No agents or LLM called.[/dim]")
    elif result.get("error"):
        con.print(f"\n  [red]No agent produced a result:[/red] {escape(result['error'])}")
    else:
        agent = result.get("agent", "unknown")
        con.print("\n  [bold cyan]TRIAGE[/bold cyan]      ESCALATED")
        scores = ", ".join(f"{a} {s:.4f}" for a, s in (result.get("agents") or {}).items())
        con.print(f"  [bold cyan]AGENTS[/bold cyan]      {escape(scores)}")
        con.print(f"  [bold cyan]TOP AGENT[/bold cyan]   {escape(agent)}")
        if result.get("auto_resolved"):
            con.print("  [bold cyan]ARBITRATION[/bold cyan] [green]AUTO-RESOLVED[/green]")
        else:
            con.print("  [bold cyan]ARBITRATION[/bold cyan] [yellow]HUMAN TIEBREAK[/yellow]")
        if result.get("pr_comment"):
            con.print(Panel(escape(str(result["pr_comment"])),
                            title="PR Comment", border_style="cyan"))
    for a, why in (result.get("skipped_agents") or {}).items():
        con.print(f"  [dim]skipped {escape(a)}: {escape(why)}[/dim]")
    con.print()


if __name__ == "__main__":
    app()

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
"""
import json as _json
import os
import sys
import webbrowser

import httpx
import typer
from rich.console import Console
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


def _api_post(path: str, params: dict | None = None) -> dict:
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{API}{path}", params=params, headers=_headers())
        r.raise_for_status()
        return r.json()


def _die_unreachable(exc: Exception) -> None:
    err.print(f"[red]Cannot reach API ({API}): {exc}[/red]")
    err.print("  Start it with: [bold]uvicorn api.main:app --reload[/bold]")
    raise typer.Exit(2)


def _emit_json(obj) -> None:
    con.print_json(_json.dumps(obj))


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
    try:
        d = _api_get("/health")
    except Exception as e:  # noqa: BLE001
        _die_unreachable(e)
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
        params["severity"] = severity
    if path:
        params["path"] = path
    try:
        d = _api_get("/findings/", params=params)
    except Exception as e:  # noqa: BLE001
        _die_unreachable(e)

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
        con.print("\n  [dim]No findings yet. Run: concord invoke[/dim]")
        return

    t = Table(show_header=True, header_style="bold", show_lines=False)
    for col in ("ID", "Severity", "Path", "Agent", "Artifact", "Age"):
        t.add_column(col)
    for f in lst:
        sev = f.get("severity", "")
        c = SEV_COLOR.get(sev, "white")
        path = f.get("path", "")
        path_str = f"[cyan]{path}[/cyan]" if "ai" in path else f"[dim]{path}[/dim]"
        t.add_row(
            f.get("id", "")[:17], f"[{c}]{sev}[/{c}]", path_str,
            f.get("agent", "—") or "—",
            (f.get("artifact", "") or "").split("/")[-1],
            f.get("timestamp", "")[:10],
        )
    con.print(t)


@app.command()
def audit(
    limit: int = typer.Option(20, "--limit", "-n"),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Show the audit trail (with correlation IDs)."""
    try:
        d = _api_get("/audit/", params={"limit": limit})
    except Exception as e:  # noqa: BLE001
        _die_unreachable(e)

    if _want_json(json):
        _emit_json(d)
        return

    entries = d.get("entries", [])
    if not entries:
        con.print("\n  [dim]No audit entries yet.[/dim]")
        return
    t = Table(show_header=True, header_style="bold", show_lines=False)
    for col in ("Finding", "Path", "Reason", "Agent", "Correlation", "Time"):
        t.add_column(col)
    for e in entries:
        t.add_row(
            e.get("finding_id", "")[:17], e.get("path", ""),
            (e.get("reason", "") or "")[:40], e.get("agent", "—") or "—",
            (e.get("correlation_id", "-") or "-")[:16],
            e.get("timestamp", "")[:19],
        )
    con.print(t)


@app.command()
def approvals(
    limit: int = typer.Option(20, "--limit", "-n"),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """List findings awaiting a human approval decision."""
    try:
        d = _api_get("/events/approvals/pending", params={"limit": limit})
    except Exception as e:  # noqa: BLE001
        _die_unreachable(e)

    if _want_json(json):
        _emit_json(d)
        return

    pending = d.get("pending", [])
    if not pending:
        con.print("\n  [green]No approvals pending.[/green]")
        return
    con.print(f"\n  [yellow]{len(pending)} finding(s) awaiting approval[/yellow]")
    t = Table(show_header=True, header_style="bold", show_lines=False)
    for col in ("ID", "Severity", "Agents", "Artifact"):
        t.add_column(col)
    for f in pending:
        sev = f.get("severity", "")
        c = SEV_COLOR.get(sev, "white")
        agents = ", ".join((f.get("result", {}).get("agents") or {}).keys())
        t.add_row(f.get("id", "")[:17], f"[{c}]{sev}[/{c}]", agents or "—",
                  (f.get("artifact", "") or "").split("/")[-1])
    con.print(t)


@app.command()
def approve(
    finding_id: str = typer.Argument(..., help="Finding ID to approve."),
    agent: str = typer.Argument(..., help="Winning agent to approve."),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Approve a finding's tiebreak by selecting the winning agent."""
    try:
        d = _api_post(f"/events/findings/{finding_id}/approve/{agent}")
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:  # noqa: BLE001
            pass
        err.print(f"[red]Approval failed ({e.response.status_code}): {detail}[/red]")
        raise typer.Exit(1)
    except Exception as e:  # noqa: BLE001
        _die_unreachable(e)

    if _want_json(json):
        _emit_json(d)
        return
    con.print(f"\n  [green]✓ Approved[/green] {finding_id} → agent [bold]{agent}[/bold]")
    if d.get("persisted"):
        con.print("  [dim]Resolution persisted and audited.[/dim]")
    if d.get("github_url"):
        con.print(f"  Issue: {d['github_url']}")


@app.command()
def reject(
    finding_id: str = typer.Argument(..., help="Finding ID to reject."),
    reason: str = typer.Option("rejected by reviewer", "--reason", "-r"),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Reject a pending finding (records a durable, audited decision)."""
    try:
        d = _api_post(f"/events/findings/{finding_id}/reject",
                      params={"reason": reason})
    except Exception as e:  # noqa: BLE001
        _die_unreachable(e)
    if _want_json(json):
        _emit_json(d)
        return
    con.print(f"\n  [red]✕ Rejected[/red] {finding_id}  [dim]({reason})[/dim]")


@app.command()
def stats(json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """One-line summary: findings, pending approvals, audit events."""
    try:
        f = _api_get("/findings/")
        p = _api_get("/events/approvals/pending")
        a = _api_get("/audit/", params={"limit": 1})
    except Exception as e:  # noqa: BLE001
        _die_unreachable(e)
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
    checks = []

    # API reachability + health
    api_ok = False
    health = {}
    try:
        health = _api_get("/health")
        api_ok = health.get("status") == "ok"
        checks.append(("API reachable", api_ok, API))
    except Exception as e:  # noqa: BLE001
        checks.append(("API reachable", False, f"{API} ({e})"))

    if api_ok:
        checks.append(("Auth enforced", bool(health.get("auth_enforced")),
                       "enforced" if health.get("auth_enforced") else "open dev mode"))

    # Local config signals
    checks.append(("CONCORD_API_KEY set", bool(API_KEY), "yes" if API_KEY else "no (dev mode)"))
    checks.append(("CONCORD_API_URL", True, API))
    checks.append(("Output mode", True,
                   "json" if os.getenv("CONCORD_OUTPUT", "").lower() == "json" else "human"))

    if _want_json(json):
        _emit_json({"checks": [{"name": n, "ok": ok, "detail": d}
                               for n, ok, d in checks],
                    "healthy": all(ok for _, ok, _ in checks if _ != "Auth enforced")})
        return

    con.print("\n  [bold]Concord diagnostics[/bold]\n")
    for name, ok, detail in checks:
        mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
        con.print(f"  {mark}  {name:<22}[dim]{detail}[/dim]")
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
    """Invoke Concord on a demo finding and show the pipeline result."""
    try:
        d = _api_post("/events/demo", params={"severity": severity.upper()})
    except Exception as e:  # noqa: BLE001
        _die_unreachable(e)

    if _want_json(json):
        _emit_json(d)
        return
    _print_result(d)


@app.command()
def agents(json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """List domain agents and whether each is wired to a real backend."""
    try:
        d = _api_get("/agents/")
    except Exception as e:  # noqa: BLE001
        _die_unreachable(e)
    if _want_json(json):
        _emit_json(d)
        return
    t = Table(title="Domain Agents", header_style="bold green")
    for col in ("Agent", "Backing", "Reliability", "Status"):
        t.add_column(col)
    for a in d.get("agents", []):
        status = a.get("status")
        badge = ("[green]● active[/green]" if status == "active"
                 else "[dim]○ planned[/dim]")
        t.add_row(a.get("domain", ""), a.get("backing", ""),
                  f"{a.get('reliability', 0):.2f}", badge)
    con.print(t)


@app.command()
def dashboard():
    """Open the Concord dashboard in your browser."""
    con.print(f"\n  Opening dashboard → [bold cyan]{API}[/bold cyan]\n")
    webbrowser.open(API)


def _print_result(result: dict):
    path = result.get("path", "unknown")
    if path == "fast_path":
        con.print(f"\n  [bold cyan]TRIAGE[/bold cyan]  FAST PATH — {result.get('reason')}")
        con.print("  [dim]No LLM call made.[/dim]")
    else:
        agent = result.get("agent", "unknown")
        res = result.get("auto_resolved")
        con.print("\n  [bold cyan]TRIAGE[/bold cyan]      ESCALATED")
        con.print(f"  [bold cyan]AGENT[/bold cyan]       {agent}")
        if res:
            con.print("  [bold cyan]ARBITRATION[/bold cyan] [green]AUTO-RESOLVED[/green]")
        else:
            con.print("  [bold cyan]ARBITRATION[/bold cyan] [yellow]HUMAN TIEBREAK[/yellow]")
        if result.get("pr_comment"):
            con.print(Panel(str(result["pr_comment"]).replace("\\n", "\n"),
                            title="PR Comment", border_style="cyan"))
    con.print()


if __name__ == "__main__":
    app()
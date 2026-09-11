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
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Show recent findings from the live API."""
    try:
        d = _api_get("/findings/", params={"limit": limit})
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
def agents():
    """List domain agents and whether each is wired to a real backend."""
    t = Table(title="Domain Agents", header_style="bold green")
    for col in ("Agent", "Backing", "Reliability", "Status"):
        t.add_column(col)
    rows = [
        ("infra",         "TerraSecure scanner", "0.92", "[green]● active[/green]"),
        ("cicd",          "Trivy · Checkov",     "0.88", "[green]● active[/green]"),
        ("security",      "source pattern scan", "0.85", "[green]● active[/green]"),
        ("kubernetes",    "kagent (MCP)",        "0.82", "[dim]○ planned[/dim]"),
        ("observability", "HolmesGPT (MCP)",     "0.80", "[dim]○ planned[/dim]"),
    ]
    for r in rows:
        t.add_row(*r)
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
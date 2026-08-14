#!/usr/bin/env python3
"""
Concord CLI — kagent-style command-line interface.
Usage (from repo root):
    python concord_cli/main.py [COMMAND] [OPTIONS]
    python concord_cli/main.py --help
"""
import asyncio
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
    add_completion=False,
    rich_markup_mode="rich",
)
con = Console()
API = os.getenv("CONCORD_API_URL", "http://localhost:8000")

SEV_COLOR = {
    "CRITICAL": "red", "HIGH": "orange3",
    "MEDIUM": "yellow", "LOW": "green",
}


@app.command()
def version():
    """Print version information."""
    con.print("[bold green]Concord[/bold green] v0.1.0")
    con.print("  AI DevSecOps Orchestration Platform")
    con.print("  github.com/BeyondBug/Concord")
    con.print(f"  API: {API}")


@app.command()
def agents():
    """List all domain agents and their current status."""
    t = Table(title="Domain Agents", header_style="bold green", show_lines=False)
    t.add_column("#",  style="dim", width=3)
    t.add_column("Agent",        style="bold")
    t.add_column("Backing Tool", style="cyan")
    t.add_column("Reliability",  justify="right")
    t.add_column("Status",       justify="center")
    t.add_column("Phase",        style="dim")

    agents = [
        ("0", "infra",        "TerraSecure (ML 92.45%)",  "0.92", "[green]● Active[/green]",  "0 → 2A"),
        ("1", "cicd",         "Trivy · Checkov",           "0.88", "[green]● Active[/green]",  "0 → 2B"),
        ("2", "kubernetes",   "kagent (Apache 2.0)",       "0.82", "[dim]○ Planned[/dim]",     "2A"),
        ("3", "observability","HolmesGPT (MIT)",           "0.80", "[dim]○ Planned[/dim]",     "2B"),
        ("4", "security",     "OPA / Semgrep",             "0.85", "[dim]○ Planned[/dim]",     "3"),
    ]
    for row in agents:
        t.add_row(*row)
    con.print(t)


@app.command()
def invoke(
    severity: str = typer.Option("CRITICAL", "--severity", "-s",
                                  help="CRITICAL | HIGH | MEDIUM | LOW"),
    finding_id: str = typer.Option("CVE-2024-33663", "--id"),
    repo: str = typer.Option("BeyondBug/CRMS", "--repo"),
):
    """Invoke Concord on a finding and show the full pipeline result."""
    c = SEV_COLOR.get(severity.upper(), "white")
    con.print(Panel(
        f"[bold]ID:[/bold] {finding_id}  "
        f"[bold]Severity:[/bold] [{c}]{severity.upper()}[/{c}]  "
        f"[bold]Repo:[/bold] {repo}",
        title="[bold green]▶ Concord Invoke[/bold green]",
        border_style="green",
    ))

    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(f"{API}/events/demo",
                            params={"severity": severity.upper()})
            r.raise_for_status()
            _print_result(r.json())
    except httpx.ConnectError:
        con.print("[yellow]  API not running — standalone mode...[/yellow]")
        asyncio.run(_standalone(severity, finding_id, repo))


def _print_result(result: dict):
    path = result.get("path", "unknown")
    if path == "fast_path":
        con.print(f"\n  [bold cyan]TRIAGE[/bold cyan]  FAST PATH — {result.get('reason')}")
        con.print("  [dim]No LLM call made. Zero inference cost.[/dim]")
    else:
        agent = result.get("agent", "unknown")
        score = result.get("score", 0)
        res = result.get("auto_resolved")
        con.print("\n  [bold cyan]TRIAGE[/bold cyan]      ESCALATED")
        con.print(f"  [bold cyan]AGENT[/bold cyan]       {agent}  (confidence {score:.4f})")
        if res:
            con.print("  [bold cyan]ARBITRATION[/bold cyan] [green]AUTO-RESOLVED[/green] — gap ≥ 0.15")
        else:
            con.print("  [bold cyan]ARBITRATION[/bold cyan] [yellow]HUMAN TIEBREAK[/yellow] — gap < 0.15")
        if result.get("pr_comment"):
            con.print()
            con.print(Panel(
                result["pr_comment"].replace("\\n", "\n"),
                title="[bold]PR Comment[/bold]",
                border_style="cyan",
            ))
    con.print()


async def _standalone(severity, finding_id, repo):
    from core.models.finding import Finding
    from core.orchestrator.orchestrator import Orchestrator
    f = Finding(
        id=finding_id, source="concord-cli",
        artifact="infra/terraform/main.tf",
        severity=severity.upper(),
        title="IAM policy allows overly permissive actions",
        description="Invoked via concord CLI (standalone)",
        raw={}, repository=repo,
    )
    result = await Orchestrator().process(f)
    _print_result(result)


@app.command()
def findings(limit: int = typer.Option(10, "--limit", "-n")):
    """Show recent findings from the live API."""
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API}/findings/", params={"limit": limit})
            r.raise_for_status()
            d = r.json()
    except Exception as e:
        con.print(f"[red]Cannot reach API ({API}): {e}[/red]")
        con.print("  Start with: [bold]uvicorn api.main:app --reload[/bold]")
        raise typer.Exit(1)

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
    t.add_column("ID",         style="dim", no_wrap=True, max_width=18)
    t.add_column("Severity")
    t.add_column("Path")
    t.add_column("Agent")
    t.add_column("Artifact",   style="dim")
    t.add_column("Age",        style="dim")

    for f in lst:
        sev = f.get("severity", "")
        c = SEV_COLOR.get(sev, "white")
        path = f.get("path", "")
        path_str = f"[cyan]{path}[/cyan]" if "ai" in path else f"[dim]{path}[/dim]"
        t.add_row(
            f.get("id","")[:17], f"[{c}]{sev}[/{c}]", path_str,
            f.get("agent","—"), (f.get("artifact","") or "").split("/")[-1],
            f.get("timestamp","")[:10],
        )
    con.print(t)


@app.command()
def dashboard():
    """Open the Concord dashboard in your default browser."""
    url = API
    con.print(f"\n  Opening dashboard → [bold cyan]{url}[/bold cyan]")
    con.print("  Make sure API is running: [bold]uvicorn api.main:app --reload[/bold]\n")
    webbrowser.open(url)


@app.command()
def get(resource: str = typer.Argument(..., help="agents | findings | stats")):
    """Get a Concord resource (like kagent get agent)."""
    if resource == "agents":
        agents()
    elif resource in ("findings", "finding"):
        findings()
    else:
        con.print(f"[red]Unknown resource: {resource}[/red]")
        con.print("Available: agents, findings")


if __name__ == "__main__":
    app()

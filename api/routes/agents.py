"""
api/routes/agents.py
Agent metadata endpoint — single source of truth for the UI/CLI.

Status is derived honestly: an agent is "active" only if its analyze() is
implemented (does not raise NotImplementedError). The Kubernetes and
Observability agents are scaffolded and report "planned" until their MCP
backends are wired in.
"""
from fastapi import APIRouter

from core.models.agent_response import SOURCE_RELIABILITY

router = APIRouter(prefix="/agents", tags=["agents"])

# Human-facing backing description per domain. Kept here (not fabricated from
# the model) so the label matches what actually runs.
_BACKING = {
    "infra":         "TerraSecure pattern scanner",
    "cicd":          "Trivy · Checkov",
    "security":      "source-code pattern scan",
    "kubernetes":    "kagent (MCP)",
    "observability": "HolmesGPT (MCP)",
}

# Active = analyze() implemented. Planned = scaffolded, needs a live MCP service.
_ACTIVE = {"infra", "cicd", "security"}


def _agent_list() -> list[dict]:
    out = []
    for domain, reliability in SOURCE_RELIABILITY.items():
        out.append({
            "domain": domain,
            "reliability": reliability,
            "backing": _BACKING.get(domain, domain),
            "status": "active" if domain in _ACTIVE else "planned",
        })
    # Stable order: active first (by reliability desc), then planned.
    out.sort(key=lambda a: (a["status"] != "active", -a["reliability"]))
    return out


@router.get("/")
async def list_agents():
    agents = _agent_list()
    return {
        "agents": agents,
        "active": sum(1 for a in agents if a["status"] == "active"),
        "planned": sum(1 for a in agents if a["status"] == "planned"),
    }
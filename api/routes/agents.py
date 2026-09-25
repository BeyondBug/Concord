"""
api/routes/agents.py
Agent metadata endpoint — single source of truth for the UI/CLI.

Status is derived, never declared:
  active  — the agent can run now. Built-in scanners are always runnable;
            kagent / HolmesGPT-backed agents only after a live probe of their
            connector succeeds.
  blocked — the backend is not usable; ``detail`` says exactly why (no
            connector declared, unreachable, agent not ready, ...).
"""
from fastapi import APIRouter
from pydantic import BaseModel

from core.models.agent_response import SOURCE_RELIABILITY

router = APIRouter(prefix="/agents", tags=["agents"])

# What actually runs behind each domain (kept honest: the infra / cicd agents
# run Concord's built-in pattern scanners, not TerraSecure / Trivy / Checkov).
_BACKING = {
    "infra":         "built-in Terraform pattern scanner",
    "cicd":          "built-in Kubernetes manifest scanner",
    "security":      "built-in source-code pattern scanner",
    "kubernetes":    "kagent (MCP)",
    "observability": "HolmesGPT (REST)",
}


class AgentInfo(BaseModel):
    domain: str
    reliability: float
    backing: str
    kind: str                 # "builtin" | "external"
    status: str               # "active" | "blocked"
    detail: str
    endpoint: str | None = None


class AgentList(BaseModel):
    agents: list[AgentInfo]
    active: int
    blocked: int


async def agent_list() -> list[AgentInfo]:
    from core.orchestrator.orchestrator import default_agents

    out = []
    for agent in default_agents():
        status_fn = getattr(agent, "status", None)
        if status_fn is None:
            kind, state, detail, endpoint = "builtin", "active", "runs in-process", None
        else:
            st = await status_fn()
            kind, state, detail, endpoint = "external", st.state, st.detail, st.url
        out.append(AgentInfo(
            domain=agent.domain,
            reliability=SOURCE_RELIABILITY.get(agent.domain, agent.source_reliability),
            backing=_BACKING.get(agent.domain, agent.domain),
            kind=kind, status=state, detail=detail, endpoint=endpoint,
        ))
    # Stable order: active first (by reliability desc), then blocked.
    out.sort(key=lambda a: (a.status != "active", -a.reliability))
    return out


@router.get("/", response_model=AgentList)
async def list_agents() -> AgentList:
    agents = await agent_list()
    return AgentList(
        agents=agents,
        active=sum(1 for a in agents if a.status == "active"),
        blocked=sum(1 for a in agents if a.status != "active"),
    )

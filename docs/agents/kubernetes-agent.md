# Kubernetes Agent

Assigned: Jash · Phase 2A · Backing tool: [kagent](https://kagent.dev) (Apache 2.0)

Concord composes kagent rather than rebuilding it: `KubernetesAgent` calls the
kagent controller's MCP endpoint (`/mcp`, Streamable HTTP) and invokes a kagent
agent (default `kagent/k8s-agent`) with the finding. The kagent agent inspects
the live cluster with its own tools and model; Concord keeps the result, scores
it deterministically (`severity_weight × 0.82`) and arbitrates it with the
other agents.

| | |
|---|---|
| Code | `agents/kubernetes/agent.py`, `agents/kubernetes/kagent_client.py`, `core/mcp_runtime/mcp_client.py` |
| Connector | `kagent` in `connectors/tools.yaml` (`http://127.0.0.1:8083/mcp`, `auth: none`) |
| Contract | kagent v0.10.x: `list_agents`, `invoke_agent {agent, task}` |
| Status | **active** only when a live probe finds `KAGENT_AGENT_REF` ready; otherwise **blocked** with the reason, and skipped by the orchestrator |
| Tests | `tests/integration/test_remote_agents.py` (contract), `tests/integration/test_live_agents.py` (live, `-m slow`) |

Current state: client, gating and wiring done; **not yet verified against a
live kagent** — see [docs/AGENTS_SETUP.md](../AGENTS_SETUP.md).

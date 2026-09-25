# Observability Agent

Assigned: rj-karan · Phase 2B · Backing tool: [HolmesGPT](https://github.com/HolmesGPT/holmesgpt) (MIT)

HolmesGPT is read-only by design (RBAC-respecting). It is a REST service — it
consumes MCP servers as toolsets but does not expose one — so
`ObservabilityAgent` calls `POST /api/chat` with the finding and uses the
returned `analysis`. Confidence is deterministic (`severity_weight × 0.80`).

| | |
|---|---|
| Code | `agents/observability/agent.py`, `agents/observability/holmesgpt.py` |
| Connector | `holmesgpt` in `connectors/tools.yaml` (`type: http`, `http://127.0.0.1:5050`, `auth: none`) |
| Contract | `GET /readyz`, `POST /api/chat {ask, model?} → {analysis, tool_calls, …}` |
| Status | **active** only when `/readyz` answers; otherwise **blocked** with the reason |
| Tests | `tests/integration/test_remote_agents.py`, `tests/integration/test_live_agents.py` (`-m slow`) |

Current state: client, gating and wiring done; **not yet verified against a
live HolmesGPT** — see [docs/AGENTS_SETUP.md](../AGENTS_SETUP.md).

# External agents: kagent (Kubernetes) and HolmesGPT (Observability)

**Status: BLOCKED on this machine** — `kind` is not installed and the Docker
daemon is not running, so no cluster exists and neither backend has been
verified live. Concord's client code, wiring and fail-safe gating are done and
tested against real protocol servers; everything below marked *not yet run* is
the exact remaining work.

| Piece | State | Evidence |
|---|---|---|
| kagent MCP client (`agents/kubernetes/kagent_client.py`) | DONE | contract tests vs a real MCP SDK server — `tests/integration/test_remote_agents.py` |
| KubernetesAgent (`agents/kubernetes/agent.py`) | DONE, gated | live probe → `active` only when `list_agents` shows `kagent/k8s-agent` |
| HolmesGPT client + ObservabilityAgent | DONE, gated | `/readyz` probe; `/api/chat` contract tests |
| Orchestrator + manifest wiring | DONE | `connectors/tools.yaml` (`kagent`, `holmesgpt`), `test_orchestrator_includes_live_backends` |
| Dashboard / CLI show `blocked` + reason | DONE | verified live, output below |
| kind cluster, kagent install, HolmesGPT install | **NOT RUN** — prerequisites missing | §3 |
| End-to-end with real kagent / HolmesGPT | **NOT VERIFIED** | `tests/integration/test_live_agents.py` skips (output below) |

## 1. The real contracts (verified against source)

Checked by reading the upstream sources cloned on 2026-09-25.

**kagent v0.10.2** (latest stable; `v1.0.0-alpha*` changes the MCP tools to
`list_agent_instances` / `invoke_agent_instance` and is not targeted).
`go/core/internal/mcp/mcp_handler.go`, `go/core/internal/httpserver/server.go`:

- Streamable HTTP MCP served by the **controller** at `/mcp`, service
  `kagent-controller`, port `8083`. No auth of its own.
- Tools: `list_agents` `{}` → `{"agents":[{"ref":"ns/name","description"}]}`;
  `invoke_agent` `{"agent":"ns/name","task":str,"context_id"?}` →
  `{"agent","text","context_id"}` (sent to the agent over A2A).
- `kagent-tools` (port 8084, `k8s_get_resources` etc.) is the *tool* server the
  agents use; Concord calls the controller's agent endpoint instead, so the
  kagent agent (with its model) does the reasoning.
- Helm: `providers.default: ollama` renders ModelConfig `default-model-config`
  (`apiVersion: kagent.dev/v1alpha2`, `spec.provider: Ollama`,
  `spec.ollama.host`), which `k8s-agent` uses (`spec.declarative.modelConfig`).

**HolmesGPT 0.42.0** (`server.py`, `helm/holmes`): a **REST** service, not an
MCP server (it consumes MCP servers as toolsets). `GET /healthz`, `GET /readyz`,
`POST /api/chat {"ask", "model"?}` → `{"analysis", "tool_calls", ...}`. Service
`<release>-holmes`, port 80 → container 5050. Models come from `modelList`;
Ollama via LiteLLM `ollama_chat/<model>` + `OLLAMA_API_BASE`.

## 2. Commands run here and their real output

### 2.1 Prerequisite check (PowerShell)

```
PS> foreach ($t in 'kind','kubectl','helm','ollama','docker') { ... Get-Command $t ... }
kind : MISSING
kubectl : C:\Program Files\Docker\Docker\resources\bin\kubectl.exe
helm : C:\Users\rjkar\AppData\Local\Microsoft\WinGet\Links\helm.exe
ollama : C:\Users\rjkar\AppData\Local\Programs\Ollama\ollama.exe
docker : C:\Program Files\Docker\Docker\resources\bin\docker.exe

PS> Invoke-WebRequest http://localhost:11434/api/tags
{"models":[{"name":"qwen2.5:14b", ... "parameter_size":"14.8B","quantization_level":"Q4_K_M",
 "context_length":32768 ...,"capabilities":["completion","tools"]}, ...]}

PS> docker info --format '{{.ServerVersion}}'
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; check if the
path is correct and if the daemon is running: open //./pipe/dockerDesktopLinuxEngine: The system
cannot find the file specified.
```

Also found: port **8080** is held by an unrelated Windows process
(`AgentService`, PID 5608) that accepts connections and never answers, so the
HolmesGPT port-forward uses local port **5050** instead.

### 2.2 Setup script — stops at the first missing prerequisite

```
$ powershell -ExecutionPolicy Bypass -File scripts/setup_local_agents.ps1

==> Checking prerequisites
Missing tools. Install them, open a new terminal, and re-run:
  winget install --id Kubernetes.kind -e
exit=1
```

### 2.3 Client contract tests (real MCP SDK server, HolmesGPT-shaped REST app)

```
$ pytest tests/integration/test_remote_agents.py -q
18 passed
```

These prove the client speaks Streamable HTTP MCP (initialize,
`notifications/initialized`, `Mcp-Session-Id`, JSON and SSE replies, tool
errors, session DELETE) and that gating is fail-safe. They do **not** prove
kagent or HolmesGPT work — that is §3.

### 2.4 Live Concord reports both agents as blocked (API on :8000)

```
$ concord agents
│ kubernetes    │ kagent (MCP)  │ 0.82 │ ○ blocked │ kagent MCP unreachable at http://127.0.0.1:8083/mcp (ConnectError: All connection attempts failed) │
│ observability │ HolmesGPT (REST) │ 0.80 │ ○ blocked │ HolmesGPT unreachable at http://127.0.0.1:5050 (ConnectError: All connection attempts failed) │
```

A real CRMS scan ran with the two agents skipped and recorded in the finding:
`skipped_agents: {"kubernetes": "blocked: kagent MCP unreachable …",
"observability": "blocked: HolmesGPT unreachable …"}`.

### 2.5 Live-backend tests

```
$ CONCORD_ALLOW_INSECURE_TRANSPORT=1 pytest tests/integration/test_live_agents.py -m slow -rs
SKIPPED tests\integration\test_live_agents.py:42: kagent not live: kagent MCP unreachable at http://127.0.0.1:8083/mcp (ConnectError: All connection attempts failed)
SKIPPED tests\integration\test_live_agents.py:53: HolmesGPT not live: HolmesGPT unreachable at http://127.0.0.1:5050 (ConnectError: All connection attempts failed)
2 skipped
```

## 3. Remaining steps (not yet run)

### 3.1 What I need from you

1. Install kind: `winget install --id Kubernetes.kind -e`
2. Start **Docker Desktop** and wait until `docker info` succeeds.
3. Then run the script (or ask me to continue):
   `powershell -ExecutionPolicy Bypass -File scripts/setup_local_agents.ps1`

No API keys are needed: both backends use your local Ollama `qwen2.5:14b`.

### 3.2 What the script does (each step checked)

```powershell
kind create cluster --config infra/local-agents/kind-config.yaml       # cluster "concord"
kubectl wait --for=condition=Ready node --all --timeout=180s
# cluster -> host networking check (pods must reach the host Ollama):
kubectl run ollama-probe --rm -i --restart=Never --image=curlimages/curl:8.10.1 `
  --command -- curl -sS -m 10 http://host.docker.internal:11434/api/version
helm upgrade --install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds `
  --version 0.10.2 --namespace kagent --create-namespace --wait
helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent `
  --version 0.10.2 --namespace kagent -f infra/local-agents/kagent-values.yaml --wait --timeout 10m
kubectl -n kagent apply -f infra/local-agents/modelconfig-ollama.yaml
kubectl -n kagent wait --for=condition=Ready agent/k8s-agent --timeout=300s
helm repo add robusta https://robusta-charts.storage.googleapis.com
helm upgrade --install holmesgpt robusta/holmes --namespace holmes --create-namespace `
  -f infra/local-agents/holmes-values.yaml --wait --timeout 10m
```

Then, in two terminals that stay open:

```powershell
kubectl -n kagent port-forward svc/kagent-controller 8083:8083
kubectl -n holmes port-forward svc/holmesgpt-holmes 5050:80
```

### 3.3 Verify end to end

```powershell
$env:CONCORD_ALLOW_INSECURE_TRANSPORT=1; $env:HOLMES_MODEL="ollama-qwen"
.venv\Scripts\python -m uvicorn api.main:app --port 8000
.venv\Scripts\python concord_cli\main.py agents          # kubernetes + observability: active
.venv\Scripts\python -m pytest tests/integration/test_live_agents.py -m slow -v -s
.venv\Scripts\python concord_cli\main.py invoke -s CRITICAL   # 5 candidates incl. kubernetes/observability
```

In the dashboard the two agents turn green in the sidebar, and each new
AI-path finding shows "Kubernetes" / "Observability" analysis cards.

### 3.4 Troubleshooting

- **Pods cannot reach Ollama** (probe step fails): Ollama binds `127.0.0.1` by
  default. `setx OLLAMA_HOST 0.0.0.0`, quit and restart the Ollama app, re-run.
  Allow port 11434 through Windows Firewall for the WSL/Docker network if asked.
- **`k8s-agent` not Ready**: `kubectl -n kagent describe agent k8s-agent` and
  `kubectl -n kagent logs deploy/k8s-agent`; usually the ModelConfig cannot
  reach Ollama (see above).
- **Slow answers / timeouts**: a 14B model on CPU can take minutes per tool
  loop. Connectors allow 300 s (`timeout_seconds` in `connectors/tools.yaml`);
  `CONCORD_AGENT_TIMEOUT` caps an agent run (default 300 s). A timeout is
  recorded as a skipped agent, never a failed scan.
- **`kagent reachable but agent 'kagent/k8s-agent' is not ready`**: the agent
  CR exists but its deployment is not Ready yet; wait, or set
  `KAGENT_AGENT_REF` to another ready agent.
- **Plaintext refused** (`InsecureTransportError`): port-forwards are
  `http://`; set `CONCORD_ALLOW_INSECURE_TRANSPORT=1` (dev only). In a real
  deployment put TLS in front and use `https://` + the manifest `tls:` block.

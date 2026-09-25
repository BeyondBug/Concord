# Concord — local kagent + HolmesGPT setup (Windows / PowerShell).
#
# Creates a kind cluster, installs kagent (Ollama provider -> host qwen2.5:14b)
# and HolmesGPT, and checks each step. Port-forwards are printed at the end
# because they must keep running in their own terminals.
#
#   powershell -ExecutionPolicy Bypass -File scripts/setup_local_agents.ps1
#
# Full walkthrough and troubleshooting: docs/AGENTS_SETUP.md
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Vals = Join-Path $Root 'infra/local-agents'
$Model = 'qwen2.5:14b'
$KagentVersion = '0.10.2'   # the kagent release Concord's client was checked against

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "`nSTOP: $msg" -ForegroundColor Red; exit 1 }

# ── 1. Prerequisites ───────────────────────────────────────────────────
Step 'Checking prerequisites'
$install = @{
  kind    = 'winget install --id Kubernetes.kind -e'
  kubectl = 'winget install --id Kubernetes.kubectl -e'
  helm    = 'winget install --id Helm.Helm -e'
  docker  = 'winget install --id Docker.DockerDesktop -e   (then start Docker Desktop)'
  ollama  = 'winget install --id Ollama.Ollama -e'
}
$missing = @()
foreach ($tool in $install.Keys) {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { $missing += $tool }
}
if ($missing) {
  Write-Host 'Missing tools. Install them, open a new terminal, and re-run:' -ForegroundColor Yellow
  foreach ($t in $missing) { Write-Host "  $($install[$t])" }
  exit 1
}
docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) { Fail 'Docker daemon is not running. Start Docker Desktop and re-run.' }
try { $tags = Invoke-RestMethod -TimeoutSec 5 http://127.0.0.1:11434/api/tags }
catch { Fail 'Ollama is not answering on 127.0.0.1:11434. Start the Ollama app and re-run.' }
if (-not ($tags.models.name -contains $Model)) { Fail "Model $Model missing. Run: ollama pull $Model" }
Write-Host "kind, kubectl, helm, docker, ollama ($Model) OK"

# ── 2. Cluster ─────────────────────────────────────────────────────────
Step 'Creating kind cluster "concord" (skipped if it exists)'
if ((kind get clusters) -notcontains 'concord') {
  kind create cluster --config (Join-Path $Vals 'kind-config.yaml')
  if ($LASTEXITCODE -ne 0) { Fail 'kind create cluster failed' }
}
kubectl config use-context kind-concord | Out-Null
kubectl wait --for=condition=Ready node --all --timeout=180s
if ($LASTEXITCODE -ne 0) { Fail 'cluster nodes not Ready' }

Step 'Checking pods can reach the host Ollama (host.docker.internal:11434)'
kubectl run ollama-probe --rm -i --restart=Never --image=curlimages/curl:8.10.1 `
  --command -- curl -sS -m 10 http://host.docker.internal:11434/api/version
if ($LASTEXITCODE -ne 0) {
  Fail ('Pods cannot reach Ollama on the host. Make Ollama listen on all interfaces: ' +
        'setx OLLAMA_HOST 0.0.0.0 ; restart the Ollama app ; re-run. See docs/AGENTS_SETUP.md.')
}

# ── 3. kagent ──────────────────────────────────────────────────────────
Step "Installing kagent CRDs + kagent $KagentVersion (Ollama provider)"
helm upgrade --install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds `
  --version $KagentVersion --namespace kagent --create-namespace --wait
if ($LASTEXITCODE -ne 0) { Fail 'kagent-crds install failed' }
helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent `
  --version $KagentVersion --namespace kagent -f (Join-Path $Vals 'kagent-values.yaml') `
  --wait --timeout 10m
if ($LASTEXITCODE -ne 0) { Fail 'kagent install failed' }
kubectl -n kagent apply -f (Join-Path $Vals 'modelconfig-ollama.yaml')
kubectl -n kagent get modelconfig
kubectl -n kagent wait --for=condition=Ready agent/k8s-agent --timeout=300s
if ($LASTEXITCODE -ne 0) { Fail 'k8s-agent did not become Ready (kubectl -n kagent describe agent k8s-agent)' }

# ── 4. HolmesGPT ───────────────────────────────────────────────────────
Step 'Installing HolmesGPT (robusta/holmes) with the Ollama model list'
helm repo add robusta https://robusta-charts.storage.googleapis.com 2>$null | Out-Null
helm repo update robusta | Out-Null
helm upgrade --install holmesgpt robusta/holmes --namespace holmes --create-namespace `
  -f (Join-Path $Vals 'holmes-values.yaml') --wait --timeout 10m
if ($LASTEXITCODE -ne 0) { Fail 'HolmesGPT install failed' }
kubectl -n holmes get pods

# ── 5. Next steps ──────────────────────────────────────────────────────
Step 'Done. Keep these two port-forwards running (one terminal each):'
Write-Host '  kubectl -n kagent port-forward svc/kagent-controller 8083:8083'
Write-Host '  kubectl -n holmes port-forward svc/holmesgpt-holmes 5050:80'
Write-Host "`nThen start Concord with plaintext localhost allowed (dev only):"
Write-Host '  $env:CONCORD_ALLOW_INSECURE_TRANSPORT=1; $env:HOLMES_MODEL="ollama-qwen"'
Write-Host '  .venv\Scripts\python -m uvicorn api.main:app --port 8000'
Write-Host '  .venv\Scripts\python concord_cli\main.py agents     # expect kubernetes/observability active'

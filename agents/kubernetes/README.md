# Kubernetes Agent

Owner: Jash  Phase: 2A (stretch)  Backing: kagent (Apache 2.0, CNCF)

kagent ships K8s/Helm/Argo/Prometheus MCP tools built-in.
We integrate it, not rebuild it.

Phase 1: static manifest scan only — no live cluster needed.
Phase 2: live cluster events via kagent MCP server on kind/k3d.

Friday demo (Oct 2026):
  K8s manifest finding from kagent flows through same orchestrator path
  as Infra findings and reaches arbitration layer.

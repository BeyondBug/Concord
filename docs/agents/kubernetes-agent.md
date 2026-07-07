# Kubernetes Agent

Owner: Jash  Phase: 2A (stretch)  Backing tool: kagent (Apache 2.0)

kagent is CNCF-track with K8s/Helm/Argo/Prometheus MCP tools built-in.
We integrate it rather than rebuild it.

Phase 1: static manifest scanning only (no live cluster needed).
Phase 2: live cluster events via kagent MCP server on kind/k3d.

Friday demo target (Oct 2026):
K8s manifest finding from kagent flows through the same orchestrator path as Infra findings.

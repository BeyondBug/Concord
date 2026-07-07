# Concord Architecture

Full diagram: docs/diagrams/architecture.png

## Layer 1 — MCP Runtime (core/mcp_runtime/)

Secure transport with mTLS and auth.
Tool registry that discovers connectors from tools.yaml at startup.
Audit log that records every action, including fast-path decisions.

## Layer 2 — Agent Orchestrator (core/orchestrator/)

Routes findings to the relevant domain agent(s).
Calls pluggable LLM backend (Ollama or BYO API key).
Context window management with tool output sanitization.

## Layer 3 — Domain Agents (agents/)

Infra agent         TerraSecure ML scanner      custom-built   Jash
CI/CD agent         Trivy + Checkov             custom-built   rj-karan
Kubernetes agent    kagent (Apache 2.0)         composed OSS   Jash
Observability agent HolmesGPT (MIT)             composed OSS   rj-karan
Security agent      OPA / Semgrep               custom-built   Both (Phase 3)

## Layer 2B — Conflict Resolution (core/arbitration/)

confidence_score = severity_weight * source_reliability
NOT self-reported LLM confidence — see design/arbitration-design.md.
Clear gap (>=0.15): auto-resolve. Close gap: human tiebreak PR comment.

## Layer 4 — Existing Tools (connectors/tools.yaml)

Not replaced. Orchestrated. Declared in tools.yaml.

# core/ — Shared Platform Components

Jointly owned. we gonna review all PRs in this directory.

models/             Finding, AgentResponse dataclasses          Phase 0
manifest/           tools.yaml loader and Pydantic schema       Phase 0
mcp_runtime/        Tool registry, transport, audit log         Phase 1
triage/             Triage gate and rule engine                 Phase 1
orchestrator/       Routing, LLM backend, context management    Phase 1
arbitration/        Confidence scoring, auto-resolve vs human   Phase 3
credential_broker/  Per-connector scoped token management       Phase 1

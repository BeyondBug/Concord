# Concord — Claude Code Instructions

This file helps Claude Code understand the project. Read it before making changes.

## What Concord is

An open-source, self-hosted AI DevSecOps orchestration platform.
Coordinates domain agents over Model Context Protocol (MCP) to automate
CI/CD security, IaC scanning, Kubernetes policy, and observability.

## Architecture

#### Layer 1: MCP Runtime     core/mcp_runtime/    transport, registry, audit log
#### Layer 2: Orchestrator    core/orchestrator/   routes tasks, calls LLM
#### Layer 3: Domain Agents   agents/<domain>/     each wraps a backing tool
#### Layer 4: Existing Tools  connectors/tools.yaml  never replaced, only orchestrated

## Ownership

core/                  Both members    Phase 0-1
agents/infra/          Jash            Phase 2A
agents/kubernetes/     Jash            Phase 2A
agents/cicd/           rj-karan        Phase 2B
agents/observability/  rj-karan        Phase 2B
agents/security/       Both            Phase 3
core/arbitration/      Both            Phase 3
infra/                 Both            Phase 4

## Key rules (never override without discussion)

- confidence_score = severity_weight * source_reliability  (NOT LLM self-report)
- Every finding including fast-path is logged to audit log
- Credential broker: per-connector scoped token, no master credential
- LLM backend is swappable via LLM_PROVIDER env var
- Rollback actions always require human approval gate

## Branches

main                    protected, merged from develop only
develop                 integration branch
feature/jash/<name>     Jash: infra + k8s agents
feature/m2/<name>       rj-karan: cicd + observability agents
feature/common/<name>   shared core work

## Friday demo rule

Every Friday: pytest tests/integration/test_e2e.py must pass.
If it fails, that is the only priority.

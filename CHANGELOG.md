# Changelog

All notable changes to Concord are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
semantic versioning once it reaches a tagged release.

## [Unreleased]

### 2026-09-25 — audit, fixes, dashboard rebuild, external-agent clients

Evidence for every item: `docs/AUDIT.md`. Suite: 142 → 194 fast tests.

#### Added
- kagent MCP client (Streamable HTTP, on `SecureTransport`) and
  `KubernetesAgent`; HolmesGPT REST client and `ObservabilityAgent`. Both are
  active only after a live probe and otherwise reported **blocked** with the
  reason and skipped — they never crash a scan. Not yet verified against live
  services (`docs/AGENTS_SETUP.md`).
- `infra/local-agents/` (kind, kagent + ModelConfig for host Ollama
  `qwen2.5:14b`, HolmesGPT values) and `scripts/setup_local_agents.ps1`.
- CLI: `scan`, `scan-status`, `finding <id>`; blocked-agent reasons.
- Dashboard: finding detail with per-agent analyses, skipped agents, scan
  summary and audit timeline; Incidents/Security/Settings on live data; API-key
  prompt; keyboard navigation.
- Real end-to-end test for the Friday flow (was `pass`), regression tests for
  every bug fixed, contract tests against a real MCP SDK server.

#### Changed
- Scans go through the orchestrator (all agents, audit, dedup) and produce one
  finding per commit; re-scanning an unchanged commit is audit-only.
- Scan severity = highest severity found (was: violation count).
- List/stat views show one row per finding (its latest decision).
- `/agents/` reports `active` / `blocked` + `detail` (was hardcoded
  `active` / `planned`).
- Manifest: `auth: bearer|none`, `timeout_seconds`, `type: mcp|http`; the broker
  honors `token_env`.

#### Fixed
- Scan route: latent `NameError`, missing audit entry, ignored `git` errors,
  event loop blocked during scans, concurrent-scan race.
- Approve/reject acting on already-decided findings (now 409); `github_url`
  not persisted; approvals impossible for demo/webhook findings.
- Dedup never fired in the API (per-request store).
- Scanners scanned nothing when given a single file; `CKV_K8S_28` matched any
  "all"; probe/limit checks fired on non-workload YAML.
- Webhook 500 on bad JSON and invented placeholder findings; `/events/demo`
  was unauthenticated and accepted any severity.
- Manifest read with the platform encoding; `.env.example` had
  `TERRASECURE_TOKEN` commented out and a non-empty `GITHUB_TOKEN` placeholder.
- CLI reported every HTTP error as "Cannot reach API"; `diagnostics` health bug.
- Dashboard: NaN timestamps, broken markup, unescaped HTML, hardcoded agents,
  success toast on failed approvals, 2-second re-render losing scroll/clicks,
  views disagreeing on counts, no API-key support.
- Docker image lacked `git` (needed by scans); `repos/` excluded from git,
  ruff and the Docker context.

### Earlier

### Added
- **SecurityPolicyAgent** with a dependency-free source-code pattern scanner
  (Python/JS/TS/Go/PHP).
- **Durable persistence**: SQLite by default, optional **PostgreSQL** backend
  selected via `CONCORD_DATABASE_URL` with graceful fallback and schema
  migration.
- **API authentication** (API key, fail-safe dev mode) and request
  **correlation IDs** threaded into logs and the audit trail.
- **MCP transport hardening**: TLS verification by default, CA bundles, mTLS,
  and refusal of plaintext URLs unless explicitly opted in.
- **Prompt-injection sanitization** of untrusted tool output before it reaches
  the LLM prompt.
- **Redis-backed dedup** with an in-memory TTL fallback.
- **Approval lifecycle**: approve, reject, and expire flows — all durable and
  audited — plus a pending-approvals queue.
- **Structured (JSON) logging** mode.
- **Web dashboard** with seven live views: Overview, Findings, Incidents, Security,
  Approvals, Audit, Settings (all read from the live API; no mock data).
- **CLI** with human and `--json` output: `health`, `findings`, `audit`,
  `approvals`, `approve`, `reject`, `stats`, `diagnostics`, `invoke`, `agents`,
  and shell-completion help.
- **Docker** multi-stage non-root image with a health check; hardened
  `docker-compose` (loopback ports, read-only rootfs, required secrets,
  service health checks).
- **Helm chart** with security context, resource limits, probes, and a
  least-privilege service account.
- **Documentation**: rewritten `README.md`, `docs/ARCHITECTURE.md`, and
  `docs/threat-model.md`.
- **CI/CD hardening**: least-privilege workflow permissions, full-suite CI,
  pinned actions, and a dependency-audit job.

### Changed
- Confidence scoring remains deterministic
  (`severity_weight × source_reliability`), never LLM self-reported.
- Audit records are now durable and correlation-tagged (previously log-only).

### Security
- Per-connector scoped credentials; no master credential.
- Human approval gate for consequential/tie-break outcomes.

### Known limitations
- Kubernetes and Observability agents are implemented but blocked until a
  cluster with kagent / HolmesGPT is running (`docs/AGENTS_SETUP.md`).
- Terraform assets under `infra/` (other than `infra/local-agents/`) remain
  placeholders.
# Changelog

All notable changes to Concord are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
semantic versioning once it reaches a tagged release.

## [Unreleased]

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
- **Web dashboard** with six live views: Overview, Findings, Security,
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
- Kubernetes and Observability agents are scaffolded but require live MCP
  services (kagent / HolmesGPT) to complete.
- Terraform assets under `infra/` remain placeholders.
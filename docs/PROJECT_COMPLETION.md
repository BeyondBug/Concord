# Concord — Project Completion Tracker

This is the canonical, **honest** implementation tracker. It reflects the actual
audited state of the repository, not aspirational completion. Statuses are:

- **DONE** — implemented and verified by a passing test or a reproduced run.
- **PARTIAL** — real code exists but is incomplete or unverified.
- **STUB** — placeholder / raises `NotImplementedError` / TODO only.
- **NOT STARTED** — described in design but no code.
- **BLOCKED** — needs an external credential/service to complete.

Last updated by an engineering session that finished **one real vertical slice**
(SecurityPolicyAgent + durable persistence) end-to-end. The rest of the tracker
records the true baseline so future work is not misled.

---

## 1. Current architecture (as it actually exists)

Four layers, matching `CLAUDE.md`:

1. **MCP runtime** — `core/mcp_runtime/` — `transport`, `registry`, `audit`.
   These are thin (~20–40 line) modules. Transport builds an authenticated
   `httpx` client per connector; registry loads connectors from the manifest;
   audit logs (and now **persists**) each decision.
2. **Orchestrator** — `core/orchestrator/` — triage → agents → arbitration →
   LLM → store. This is the most complete part of the system and is real.
3. **Domain agents** — `agents/<domain>/` — each wraps a backing scan.
4. **Connectors** — `connectors/tools.yaml` — declarative manifest only.

Data unit: `core/models/finding.py::Finding`. Agent output:
`core/models/agent_response.py::AgentResponse`.

Confidence is deterministic (`severity_weight * source_reliability`), **not**
LLM self-report — this invariant is preserved and tested.

---

## 2. Audited component status

| Area | Problem / State | Severity | Current State | Required Change | Files | Impl Status | Tests | Verification |
|------|-----------------|----------|---------------|-----------------|-------|-------------|-------|--------------|
| Triage gate + rules | Works; dedup is a stub | Low | Real | Redis-backed dedup later | `core/triage/**` | PARTIAL | yes | `test_triage.py` passes |
| Arbitration + confidence | Works, deterministic formula | — | Real | none | `core/arbitration/**` | DONE | yes | `test_arbitration.py`, `test_confidence.py` |
| Orchestrator flow | Real; used to swallow store errors silently | Med | Real | **Fixed** — errors now logged, not swallowed | `core/orchestrator/orchestrator.py` | DONE | yes | `test_orchestrator.py` + new persistence tests |
| InfraAgent / CICDAgent | Real regex scans (TF / K8s) | — | Real | swap for MCP later | `agents/infra`, `agents/cicd` | PARTIAL | indirect | drive via demo endpoint |
| **SecurityPolicyAgent** | Was `NotImplementedError` | High | **Implemented** | source-code policy scan | `agents/security/agent.py`, `core/scanner.py` | **DONE** | yes | `test_security_agent.py`, `test_source_scanner.py` |
| kubernetes / observability agents | Wrappers exist, backing clients unverified | Med | STUB/PARTIAL | implement or gate behind connector | `agents/kubernetes`, `agents/observability` | STUB | no | — |
| Persistence (findings) | In-memory dict only; lost on restart | High | **Replaced** | durable SQLite store | `core/persistence/**`, `api/routes/findings.py` | **DONE** | yes | `test_persistence.py` |
| Persistence (audit) | Log-only; not queryable | High | **Replaced** | durable SQLite store | `core/persistence/**`, `api/routes/audit.py`, orchestrator | **DONE** | yes | `test_persistence.py` |
| API routes | Thin; `/audit` returned empty | Med | Improved | wire to store | `api/routes/**` | PARTIAL | smoke | TestClient smoke passes |
| API auth | `middleware/auth.py` exists but not wired into `main.py` | High | STUB | wire + document | `api/main.py`, `api/middleware/auth.py` | STUB | no | — |
| MCP transport | No TLS verify config, no mTLS | Med | PARTIAL | add verify + mTLS (TODO in code) | `core/mcp_runtime/transport.py` | PARTIAL | no | — |
| Credential broker | Scoped per-connector env tokens, no master | — | Real | rotation readiness | `core/credential_broker/broker.py` | PARTIAL | no | — |
| `context.sanitize_tool_output` | Only truncates length; labeled as injection defense | Med | STUB | real sanitization | `core/orchestrator/context.py` | STUB | no | — |
| CLI | Single Typer file | Med | PARTIAL | expand + JSON mode | `concord_cli/main.py` | PARTIAL | no | — |
| Web dashboard | One static HTML file | Med | PARTIAL | real frontend later | `api/templates/dashboard.html` | PARTIAL | no | — |
| Approvals workflow | `/approve` endpoint exists; GitHub-gated | Med | PARTIAL | UI + audit of approval | `api/routes/scan.py` | PARTIAL | no | — |
| Docker / Helm / Terraform | Present, minimal, unhardened | Med | PARTIAL | security hardening | `Dockerfile`, `helm/**`, `infra/**` | PARTIAL | no | — |
| `utcnow()` deprecation | Throughout production code | Low | **Fixed in prod code** | timezone-aware | orchestrator, persistence | DONE | n/a | ruff clean |

---

## 3. What this session actually changed (verified)

### Implemented
- **`SecurityPolicyAgent`** (`agents/security/agent.py`) — replaced the
  `NotImplementedError` stub with a real, dependency-free source-code policy
  scan. Has an explicit contract (purpose, inputs, output, error/timeout
  behaviour, permission model) documented in its docstring.
- **`SourceCodeScanner`** (`core/scanner.py`) — new Semgrep-style pattern
  scanner for Python / JS / TS / Go / PHP covering eval/exec, `shell=True`,
  `os.system`, `pickle.loads`, unsafe `yaml.load`, `child_process.exec`, PHP
  shell sinks, and hardcoded secrets. Language-scoped to limit false positives,
  skips vendored/generated trees.
- **Durable persistence** (`core/persistence/store.py`) — SQLite-backed store
  for findings and audit entries, swappable behind `get_store()`, configurable
  via `CONCORD_DB_PATH` (`:memory:` supported). Replaces the in-memory-only
  finding store and the log-only audit path.
- **Orchestrator wiring** — the security agent now participates in every
  AI-path run; findings and audit records are persisted; storage failures are
  **logged**, never silently swallowed (previous `except: pass`).
- **API** — `/findings` and `/audit` now read the durable store; `/audit` no
  longer returns a hardcoded empty list.

### Fixed
- Silent exception swallowing in `Orchestrator._store`.
- `/audit` endpoint returning empty placeholder data.
- `datetime.utcnow()` deprecation in production code paths.
- `.gitignore` now excludes the SQLite DB files.

### Tests added (19 new, 37 total passing)
- `tests/unit/test_source_scanner.py` (8) — detection, language scoping,
  clean-code, vendored-dir skipping, missing-path safety.
- `tests/integration/test_security_agent.py` (4) — agent contract, vulnerable
  vs clean source, missing-artifact resilience.
- `tests/integration/test_persistence.py` (7) — CRUD, ordering, stats,
  audit persistence, limit bounds, and orchestrator persistence + the
  "every finding is audited, including fast-path" invariant.
- `tests/conftest.py` — isolates the global store to in-memory per test.

---

## 4. Verification status (this session)

| Check | Command | Result |
|-------|---------|--------|
| Lint | `ruff check .` | PASS (clean) |
| Unit + integration tests | `pytest tests/` | 37 passed |
| API smoke | FastAPI `TestClient` demo → findings → audit | PASS (data persisted + readable) |
| Orchestrator run | security agent scores 0.85 and enters arbitration | PASS (verified in logs) |
| No stray artifacts | `ls *.db` | none committed |

---

## 5. Prioritized remaining roadmap (honest)

**P0 (security / correctness)**
- Wire `api/middleware/auth.py` into `api/main.py` and document the auth model.
- Add TLS verification (and optional mTLS) to `SecureTransport`.
- Replace `context.sanitize_tool_output` truncation stub with real prompt-injection defenses, or rename it to reflect what it does.

**P1 (core functionality)**
- Implement or connector-gate the kubernetes / observability agents.
- Redis-backed dedup rule (currently a stub).
- Persist approval decisions and their outcomes to the audit table.

**P2 (reliability / ops)**
- PostgreSQL backend behind the same `get_store()` API for multi-process deploys.
- Harden Dockerfile (non-root, multi-stage), Helm (securityContext, limits), Terraform.
- Structured logging with correlation IDs.

**P3 (product polish)**
- Real web dashboard (framework TBD) beyond the single static HTML page.
- Expanded CLI with `--json` machine mode and richer subcommands.

---

## 6. Known limitations / non-fabrication notes

- The SQLite backend is single-process appropriate. Concurrent multi-process
  deployments need the PostgreSQL backend (not yet built).
- The kubernetes/observability agents are **not** verified end-to-end; their
  backing clients require external services/credentials (BLOCKED locally).
- The dashboard and CLI remain early; they are not production UIs yet.
- No fabricated metrics, connectors, or "works" claims appear in this document.
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
| Triage gate + rules | Works; dedup now real | Low | Real | none pending | `core/triage/**` | DONE | yes | `test_triage.py`, `test_dedup.py` |
| Arbitration + confidence | Works, deterministic formula | — | Real | none | `core/arbitration/**` | DONE | yes | `test_arbitration.py`, `test_confidence.py` |
| Orchestrator flow | Real; used to swallow store errors silently | Med | Real | **Fixed** — errors now logged, not swallowed | `core/orchestrator/orchestrator.py` | DONE | yes | `test_orchestrator.py` + new persistence tests |
| InfraAgent / CICDAgent | Real regex scans (TF / K8s) | — | Real | swap for MCP later | `agents/infra`, `agents/cicd` | PARTIAL | indirect | drive via demo endpoint |
| **SecurityPolicyAgent** | Was `NotImplementedError` | High | **Implemented** | source-code policy scan | `agents/security/agent.py`, `core/scanner.py` | **DONE** | yes | `test_security_agent.py`, `test_source_scanner.py` |
| kubernetes / observability agents | Wrappers exist, backing clients unverified | Med | STUB/PARTIAL | implement or gate behind connector | `agents/kubernetes`, `agents/observability` | STUB | no | — |
| Persistence (findings) | In-memory dict only; lost on restart | High | **Replaced** | durable SQLite + optional PostgreSQL backend | `core/persistence/**`, `api/routes/findings.py` | **DONE** | yes | `test_persistence.py`, `test_postgres_store.py` |
| Persistence (audit) | Log-only; not queryable | High | **Replaced** | durable SQLite store | `core/persistence/**`, `api/routes/audit.py`, orchestrator | **DONE** | yes | `test_persistence.py` |
| API routes | Thin; `/audit` returned empty | Med | Improved | wire to store | `api/routes/**` | PARTIAL | smoke | TestClient smoke passes |
| API auth | `middleware/auth.py` exists but not wired into `main.py` | High | **Implemented** | API-key dependency + fail-safe dev mode | `api/main.py`, `api/middleware/auth.py`, `api/middleware/logging.py` | **DONE** | yes | `test_auth.py` (11) + live smoke |
| MCP transport | No TLS verify config, no mTLS | Med | **Hardened** | https-by-default, CA bundle, mTLS, insecure opt-in | `core/mcp_runtime/transport.py`, `core/models/manifest.py` | **DONE** | yes | `test_transport_security.py` (14) |
| Credential broker | Scoped per-connector env tokens, no master | — | Real | rotation readiness | `core/credential_broker/broker.py` | PARTIAL | no | — |
| `context.sanitize_tool_output` | Only truncated length; labeled as injection defense | Med | **Implemented + wired** | real sanitization, delimiting, flagging; used in LLM path | `core/orchestrator/context.py`, `core/orchestrator/orchestrator.py` | **DONE** | yes | `test_sanitize.py` (11) |
| Dedup triage rule | Redis TODO; always returned no-match | Med | **Implemented** | Redis store + in-memory TTL fallback | `core/triage/rules/dedup.py`, `core/triage/rules/dedup_store.py` | **DONE** | yes | `test_dedup.py` (11) |
| `utcnow()` deprecation | Remained in `finding.py`, `scan.py`, tests | Low | **Fixed everywhere** | timezone-aware `datetime.now(UTC)` | `core/models/finding.py`, `api/routes/scan.py`, tests | **DONE** | n/a | suite warning-free (only 3rd-party warnings remain) |
| CLI | Typer CLI; no JSON mode, few commands | Med | **Expanded** | --json machine mode, audit/approvals/approve/health commands, exit codes, no-color safe | `concord_cli/main.py` | **DONE** | yes | `test_cli.py` (12) + live smoke |
| Web dashboard | One static HTML, findings-only | Med | **Extended (read-only)** | tabbed Findings/Approvals/Audit views on live API, no mock data | `api/templates/dashboard.html` | **PARTIAL→DONE (read views)** | manual+live | live smoke: 3 endpoints render real data |
| Approvals workflow | `/approve` mutated a copy; no persist, no audit | High | **Fixed** | durable resolution + audit record + pending-list API + candidate guard | `api/routes/scan.py`, `core/persistence/store.py` | **DONE** | yes | `test_approvals.py` (7) + live smoke |
| Docker / Helm / Terraform | Present, minimal, unhardened | Med | **Hardened (Docker+Helm)** | multi-stage non-root image, healthcheck, .dockerignore; compose loopback+read-only+healthchecks; real Helm templates w/ securityContext, probes, resources, SA | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `helm/concord/**` | **DONE (unverified build)** | n/a | YAML structure checked; `docker build`/`helm template` not runnable in sandbox |
| `utcnow()` deprecation | Throughout production code | Low | **Fixed in prod code** | timezone-aware | orchestrator, persistence | DONE | n/a | ruff clean |

---

## 3. What this session actually changed (verified)

### Slice 12 — dashboard Approvals + Audit views + startup fix (this session)

**Latency fix (from a real observation):** with `POSTGRES_URL` set but no
Postgres running, the first finding write blocked ~7.4s on the connection
timeout *inside the request*. The store is now built in a FastAPI **lifespan**
startup handler, so the one-time fallback happens at boot. Measured: same
request dropped from 7.4s to 0.027s.

**Dashboard (read-only, real API, no mock data)**
- **`api/templates/dashboard.html`** — added a tabbed nav (Findings / Approvals
  / Audit). The existing findings view is unchanged. New **Approvals** view
  lists `/events/approvals/pending` with inline approve buttons (reusing the
  existing approve call); new **Audit** view renders `/audit/` including the
  correlation IDs from slice 10. A live count badge shows pending approvals.
  All data comes from the live API; empty states render when the API is empty.
  HTML output is escaped to avoid injection from finding fields.

**Verified live:** dashboard served with all views; `/findings/`,
`/events/approvals/pending`, `/audit/` all return real, renderable data
(2 findings, 1 pending, 2 audit rows with correlation IDs). Startup fallback
confirmed fast.

**Honest scope:** these are **read-only views** (plus the existing approve
action) wired to real endpoints — not the full "premium" multi-view dashboard
from the task doc. No AI-assistant view, incidents, k8s, IaC, or settings pages;
those remain future work. Nothing is faked.

---


### Slice 11 — CLI expansion with JSON mode (this session)

**Implemented** (extends the existing Typer CLI; all prior commands kept)
- **`concord_cli/main.py`** — added `--json` machine-readable mode to every data
  command (or `CONCORD_OUTPUT=json`); colour auto-disabled when stdout is not a
  TTY or `NO_COLOR` is set, so piped output is never decorated. New commands:
  `health`, `audit` (shows correlation IDs), `approvals` (pending queue),
  `approve <finding> <agent>`. Shared API-client helpers send the API key from
  `CONCORD_API_KEY`. Distinct exit codes: 1 for a rejected action, 2 for an
  unreachable API.

**Tests added (12; 121 total):** `tests/unit/test_cli.py` — table + JSON output
for health/findings/audit/approvals, approve success + 400 rejection exit code,
unreachable-API exit code, and agents listing, via Typer's CliRunner with the
API helpers monkeypatched (no live server needed).

**Verified live:** against a running API, `health/findings/audit --json` produce
clean JSON parsed by a separate process (no decoration leak).

---


### Slice 9 — PostgreSQL backend behind get_store() (this session)

**Implemented**
- **`core/persistence/postgres_store.py`** — `PostgresStore`, API-compatible
  with `SQLiteStore` (same method set/return shapes), on psycopg 3 (sync) with a
  connection pool and a bounded connect timeout. JSONB result column.
- **`core/persistence/store.py`** — `get_store()` now selects the backend:
  PostgreSQL when `CONCORD_DATABASE_URL`/`POSTGRES_URL` is set **and reachable**,
  otherwise SQLite. Any connection failure logs a warning and **falls back to
  SQLite** (fail-safe) — a broken Postgres never takes the platform down.
- **`requirements/base.txt`** — added `psycopg[binary,pool]>=3.1`.
- **`.env.example`** — documents `CONCORD_DATABASE_URL` / `CONCORD_DB_PATH`.
- **`pyproject.toml`** — registered a `slow` pytest marker.

**Tests added (11; 101 total, 1 slow):** `tests/integration/test_postgres_store.py`
— backend selection + fallback (mocked and real bounded timeout), and
`PostgresStore` SQL/row-shaping via a fake connection pool.

**Honest limitation:** no PostgreSQL server is available in this environment, so
the store was **not** exercised against a live database. SQL logic and the
selection/fallback path are tested without a server; run the live check once via
docker-compose: `docker compose up -d postgres` then
`CONCORD_DATABASE_URL=postgresql://concord:...@localhost/concord pytest -m slow`.

---


### Slice 8 — Docker + Helm hardening + approval-test fix (this session)

**Test fix:** `tests/integration/test_approvals.py` failed when the shell had
`CONCORD_API_KEY` set (protected routes returned 401). The `client` fixture now
explicitly clears the key and reloads auth, so the suite is deterministic
regardless of environment. Verified: 91 pass both with and without the key set.

**Docker (hardened; not build-verified in sandbox — no docker available)**
- `Dockerfile`: multi-stage (venv built separately, no toolchain in the final
  image), runs as a non-root `concord` user, `HEALTHCHECK` on `/health`,
  `PYTHONDONTWRITEBYTECODE`/`PYTHONUNBUFFERED`, `CONCORD_DB_PATH=/data`.
- `.dockerignore`: excludes `.git`, `.venv`, caches, `*.db`, `.env`, tests, docs.
- `docker-compose.yml`: ports bound to `127.0.0.1` only, `POSTGRES_PASSWORD`
  required (no weak default), healthchecks + `depends_on: condition:
  service_healthy`, `read_only: true` + `tmpfs` + `cap_drop: ALL` +
  `no-new-privileges` on the api service, named data volume.
- `docker-compose.override.yml.example`: documented dev hot-reload override.

**Helm (was two `# TODO Phase 4` stubs; YAML structure checked, not
`helm template`-verified — no helm available)**
- `deployment.yaml`: pod + container `securityContext` (runAsNonRoot,
  readOnlyRootFilesystem, drop ALL caps, seccomp RuntimeDefault),
  `automountServiceAccountToken: false`, resource requests/limits, liveness +
  readiness probes on `/health`, writable `emptyDir` for `/data` and `/tmp`,
  optional `envFromSecret` for secrets.
- `service.yaml`: real ClusterIP service with named port.
- `serviceaccount.yaml`: distinct least-privilege SA, no RBAC bindings.
- `values.yaml`: expanded to drive all of the above.

**Honest limitation:** `docker build` and `helm template`/`helm lint` are not
runnable in this environment (no docker/helm, and get.helm.sh is not in the
network allowlist). Structure was validated and logic reviewed; the operator
must run the verification commands (below) once before trusting the images.

---

### Slice 6+7 — auditable approvals + pending-approvals API (this session)

**Problem found:** the `/approve` endpoint mutated a *deserialized copy* of the
stored result (which never reached the durable store) and wrote nothing to the
audit log — so human approvals were neither persisted nor auditable, violating
the "every decision is logged" invariant. There was also no way to list what
was awaiting a human.

**Implemented**
- **`core/persistence/store.py`** — `update_finding_result()` (durably replace a
  finding's result JSON + agent) and `list_pending_approvals()` (AI-path,
  `auto_resolved is False`, not yet approved).
- **`api/routes/scan.py`** — approve endpoint now: persists the resolution via
  `update_finding_result`, writes an `AuditRecord` (`human_approved:<agent>`),
  and rejects approving an agent that wasn't a tiebreak candidate (400). New
  `GET /events/approvals/pending` lists findings awaiting a human. Returns a
  `persisted` flag.

**Tests added (7):** `tests/integration/test_approvals.py` — store update +
missing-row, pending filtering, API approve persists+audits, 404, non-candidate
rejection, and pending list clearing after approval. Verified live end-to-end.

---

### Slice 5 — Redis-backed dedup + suite cleanup (this session)

**Implemented**
- **`core/triage/rules/dedup_store.py`** — fingerprint stores for dedup. A
  finding fingerprint is a SHA-256 over its identity (id/source/artifact/
  severity), deliberately excluding the volatile timestamp. `RedisDedupStore`
  uses atomic `SET NX EX` (shared across processes); `InMemoryDedupStore` is a
  per-process TTL fallback. `get_dedup_store()` picks Redis when `REDIS_URL` is
  reachable and **gracefully falls back** to in-memory otherwise (fail-safe —
  triage never crashes on a missing service).
- **`core/triage/rules/dedup.py`** — `DedupRule` now records fingerprints and
  fast-paths duplicates seen within the TTL. No-arg constructor preserved for
  the orchestrator; a store can be injected in tests.

**Tests added (11):** `tests/unit/test_dedup.py` — fingerprint stability,
in-memory first-unseen-then-seen, TTL, Redis fallback (unset + unreachable),
rule behaviour, and Redis semantics against a fake client.

**Cleanup:** removed all `datetime.utcnow()` deprecations from Concord code
(`core/models/finding.py`, `api/routes/scan.py`) and the test suite. The suite
is now warning-free except two third-party (Starlette/anyio) warnings.

### Slice 4 — real prompt-injection sanitization (this session)

**Implemented**
- **`core/orchestrator/context.py`** — `sanitize_tool_output` replaced the
  truncate-only stub with real defenses: length cap, control-char and
  zero-width/bidi stripping, neutralized role/protocol markers and code fences,
  and injection-phrase flagging. Output is always wrapped in an explicit
  `UNTRUSTED_TOOL_OUTPUT` delimiter so the prompt can mark it as data. Scope and
  residual risk are documented in the module (defense-in-depth, not a guarantee;
  relies on the system prompt + the existing human approval gate).
- **`core/orchestrator/orchestrator.py`** — the sanitizer is now **wired into
  the LLM path**: untrusted `finding.title`/`finding.description` are sanitized
  before being sent to the model (previously they were declared-but-unused).

**Tests added (11):** `tests/unit/test_sanitize.py` — delimiting, length cap,
control/zero-width/bidi stripping, marker neutralization, fence downgrade,
injection flagging (kept-not-dropped), clean passthrough, coercion.

---

### Slice 3 — MCP transport TLS hardening (this session)

**Implemented**
- **`core/mcp_runtime/transport.py`** — `SecureTransport` is now secure by
  default: TLS verification on, optional per-connector CA bundle, optional
  mTLS (client cert/key), and plaintext `http://` URLs **rejected** unless
  `CONCORD_ALLOW_INSECURE_TRANSPORT=1` is set (logged loudly). Unknown/relative
  URL schemes are refused rather than guessed. Scoped bearer token still comes
  from the per-connector broker and is never logged. Original `get_client`
  signature preserved; added `get_client_for(connector)`.
- **`core/models/manifest.py`** — added an **optional** `ConnectorTLS` block
  (`ca_bundle`, `client_cert`, `client_key`, `verify`). Backward compatible:
  the existing `tools.yaml` still validates unchanged.
- **`connectors/tools.yaml`** — documented TLS/mTLS example (commented).
- **`.env.example`** — documents `CONCORD_ALLOW_INSECURE_TRANSPORT`.

**Tests added (14 new; 62 total passing)**
- `tests/integration/test_transport_security.py` — scheme enforcement
  (http rejected/opt-in/https/unknown/relative), token scoping, CA-bundle and
  mTLS wiring, and `get_client_for` applying the same guard.

**Note:** no agent calls `SecureTransport` yet (agents use local scanners), so
this hardening had no callers to break — it makes the interface safe for when
the kubernetes/observability MCP connectors are wired in.

---

### Slice 2 — API authentication + request correlation (this session)

**Implemented**
- **`api/middleware/auth.py`** — API-key authentication as a FastAPI
  dependency. Key from `CONCORD_API_KEY`, presented via `Authorization: Bearer`
  or `X-API-Key`. Constant-time comparison; key never logged. **Fail-safe dev
  mode**: unset key → open mode with a loud warning (never a silent default).
- **`api/middleware/logging.py`** — per-request correlation IDs (`X-Request-ID`,
  honoring inbound IDs) and method/path/status/duration logging. No secrets logged.
- **`api/main.py`** — logging middleware applied globally; `require_api_key`
  guards `/findings`, `/audit`, and the scan/approve routes; `/health`, `/`,
  and the HMAC-verified `/events/github` webhook stay public by design.
  `/health` now reports `auth_enforced`.
- **`.env.example`** — documents `CONCORD_API_KEY` with a generation command.

**Tests added (11 new; 48 total passing)**
- `tests/integration/test_auth.py` — open dev mode, enforced mode, missing/wrong
  key, Bearer and X-API-Key acceptance, audit route protection, public routes
  staying open, webhook remaining key-free, and correlation-ID header presence.

**Verified:** live smoke test — protected routes 401 without/with wrong key,
200 with the right key; public demo endpoint 200; `X-Request-ID` emitted.

---

### Slice 1 — SecurityPolicyAgent + durable persistence (prior session)


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
| Unit + integration tests | `pytest tests/` | 121 passed (1 slow) |
| API smoke | FastAPI `TestClient` demo → findings → audit | PASS (data persisted + readable) |
| Orchestrator run | security agent scores 0.85 and enters arbitration | PASS (verified in logs) |
| No stray artifacts | `ls *.db` | none committed |

---

## 5. Prioritized remaining roadmap (honest)

**P0 (security / correctness)**
- ~~Wire `api/middleware/auth.py` into `api/main.py`~~ — **DONE** (slice 2).
- ~~Add TLS verification (and optional mTLS) to `SecureTransport`~~ — **DONE** (slice 3).
- ~~Replace `context.sanitize_tool_output` truncation stub~~ — **DONE** (slice 4).

**P1 (core functionality)**
- Implement or connector-gate the kubernetes / observability agents.
- ~~Redis-backed dedup rule~~ — **DONE** (slice 5).
- ~~Persist approval decisions and their outcomes to the audit table~~ — **DONE** (slice 6+7).

**P2 (reliability / ops)**
- ~~PostgreSQL backend behind the same `get_store()` API~~ — **DONE** (slice 9, live-DB-unverified).
- ~~Harden Dockerfile (non-root, multi-stage), Helm (securityContext, limits), Terraform~~ — Docker + Helm **DONE** (slice 8, build-unverified); Terraform still pending.
- Structured logging with correlation IDs.

**P3 (product polish)**
- Real web dashboard (framework TBD) beyond the single static HTML page.
- ~~Expanded CLI with `--json` machine mode and richer subcommands~~ — **DONE** (slice 11).

---

## 6. Known limitations / non-fabrication notes

- The SQLite backend is single-process appropriate. Concurrent multi-process
  deployments need the PostgreSQL backend (not yet built).
- The kubernetes/observability agents are **not** verified end-to-end; their
  backing clients require external services/credentials (BLOCKED locally).
- The dashboard and CLI remain early; they are not production UIs yet.
- No fabricated metrics, connectors, or "works" claims appear in this document.
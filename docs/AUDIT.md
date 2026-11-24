# Concord — Codebase Audit (2026-09-25)

Scope: the entire repository at commit `5c3933f` (branch
`feat/premium-ui-completion`), excluding `repos/` (scanned targets). Line
references below are **to that baseline commit** unless marked otherwise. Every
"works" claim was verified by running it; every bug has the file:line where it
lives and what happened when it was exercised.

## 1. Baseline (measured before any change)

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check .` | `All checks passed!` |
| Fast tests | `CONCORD_DB_PATH=:memory: pytest tests/ -q -m "not slow"` | **142 passed, 1 deselected** in 6.99s |
| Interpreter | `.venv/Scripts/python --version` | Python 3.14.2 |

Environment probed for the external agents (Step 4):

| Tool | Found |
|---|---|
| kubectl | `C:\Program Files\Docker\Docker\resources\bin\kubectl.exe` |
| helm | `C:\Users\rjkar\AppData\Local\Microsoft\WinGet\Links\helm.exe` |
| ollama | running on `127.0.0.1:11434`, `qwen2.5:14b` present (capabilities: completion, tools) |
| docker CLI | present — **daemon not running** (`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.`) |
| kind | **missing** |

## 2. What actually worked at baseline (verified)

| Area | Evidence |
|---|---|
| Triage gate + severity / known-pattern rules | `tests/unit/test_triage.py` passes; LOW → fast path reproduced via `POST /events/demo?severity=LOW` |
| Deterministic confidence `severity_weight × source_reliability` | `core/models/agent_response.py:35-44`, `tests/unit/test_confidence.py` |
| Arbitration (gap ≥ 0.15 auto, else human) | `core/arbitration/resolver.py:7-24`, `tests/unit/test_arbitration.py` |
| Built-in scanners (Terraform, K8s YAML, source) | `core/scanner.py`; ran against `tests/fixtures/terraform` and the CRMS checkout |
| Durable SQLite findings + audit with correlation ids | `core/persistence/store.py`, `tests/integration/test_persistence.py` |
| API-key auth dependency, request-id middleware | `api/middleware/auth.py`, `api/middleware/logging.py`, `tests/integration/test_auth.py` |
| Transport TLS guard (https by default, opt-in http) | `core/mcp_runtime/transport.py:79-100`, `tests/integration/test_transport_security.py` |
| Prompt-injection sanitizer | `core/orchestrator/context.py`, `tests/unit/test_sanitize.py` |
| Approve / reject / expire endpoints (happy path) | `api/routes/scan.py:36-189`, `tests/integration/test_approvals.py` |

## 3. Stubs, TODOs and dead code at baseline

| Location | What |
|---|---|
| `agents/kubernetes/agent.py:17-19` | `raise NotImplementedError("KubernetesAgent.analyze() — Phase 2A")` |
| `agents/kubernetes/kagent_client.py:1-4` | comment-only file (TODO) |
| `agents/observability/agent.py:17-19` | `raise NotImplementedError("ObservabilityAgent.analyze() — Phase 2B")` |
| `agents/observability/holmesgpt.py:1-2` | comment-only file (TODO) |
| `agents/infra/mcp_server.py`, `agents/infra/terrasecure.py` | comment-only TODO files |
| `agents/cicd/checkov.py`, `agents/cicd/trivy.py` | comment-only TODO files |
| `core/mcp_runtime/audit.py:24` | `TODO Phase 1: persist to PostgreSQL` (persistence actually happens in the orchestrator) |
| `core/mcp_runtime/registry.py:17-18` | `TODO` health-check / metrics per connector |
| `api/routes/scan.py:14` | "In-memory scan state (Phase 1: replace with Redis/DB)" |
| `tests/integration/test_e2e.py:8-10` | the Friday e2e test was `pass` |
| `tests/integration/test_{k8s,obs,infra,cicd}_agent.py` | comment-only files, no tests |
| `core/orchestrator/router.py` | `Router` is never called anywhere |
| `core/checkov_utils.py`, `core/github_utils.py:51 format_issue_body` | never imported / called |
| `connectors/tools.yaml` terrasecure / trivy / checkov | declared, but no code calls them — the infra/cicd agents run the built-in regex scanners |

## 4. Bugs found (all fixed; regression test named)

### Backend

| # | Location (baseline) | Bug | Reproduction / effect | Fix + test |
|---|---|---|---|---|
| B1 | `api/routes/scan.py:285,304` | `t, s` only assigned in the tiebreak branch but used unconditionally when storing → `NameError` whenever a scan auto-resolves | latent: with infra 0.92 vs cicd 0.88 the gap is always < 0.15, so it never fired yet | scan route now uses the orchestrator; `test_scan_clones_analyzes_and_is_idempotent` |
| B2 | `api/routes/scan.py:192-315` | scan findings were stored but **never audited** — violates "every finding is logged to the audit log" | audit table empty after a scan | via orchestrator; same test asserts the audit trail |
| B3 | `api/routes/scan.py:236` | finding id = timestamp → every click on Scan created a **new duplicate finding** | two scans → two identical CRMS rows in the dashboard | id derived from commit (`CRMS-<sha12>`), re-scan is audit-only; live re-scan verified (§6) |
| B4 | `api/routes/scan.py:211-218` | `git clone/pull` return codes ignored; `git -C repos/crms` inside this repo silently resolves to **Concord's own repo** when `repos/crms` is not a checkout | a failed clone produced a "0 violations" finding | return codes checked, `.git` required; `test_scan_clone_failure_is_reported` |
| B5 | `api/routes/scan.py:212-227` | blocking `subprocess.run` and file scans inside an `async` task — froze the event loop (all API requests) during a scan | — | `asyncio.to_thread` |
| B6 | `api/routes/scan.py:21-26` | check-then-set race on scan state | two quick clicks → two scans | `asyncio.Lock`, 409 on concurrent trigger; `test_scan_rejects_concurrent_trigger` |
| B7 | `api/routes/scan.py:233` | severity from violation **count** (11 MEDIUMs → CRITICAL) | — | severity = highest severity found (LOW when clean) |
| B8 | `api/routes/scan.py:36-108,119-148` | approve/reject accepted findings that were already approved, rejected, expired or fast-path; `github_url` never stored | approving twice rewrote the decision | 409 unless pending; `test_approve_twice_is_409`, `test_reject_after_approve_is_409`, `test_approve_fast_path_finding_is_409` |
| B9 | `core/orchestrator/orchestrator.py:75-81` | AI-path results had no `agents` candidates → the approve guard (`scan.py:53-54`) was skipped (any agent accepted) and the Approvals UI showed **no approve buttons** for demo/webhook findings | `POST /events/demo` → pending item with only "reject" | results carry `agents` + `analyses`; `test_ai_result_carries_candidates_for_approval` |
| B10 | `core/orchestrator/orchestrator.py:51-52` | "no agent responses" returned without storing or auditing | — | stored + audited; `test_no_agents_is_stored_and_audited` |
| B11 | `core/orchestrator/orchestrator.py:27` + `core/triage/rules/dedup.py:23` | each request builds a new `Orchestrator` → new `DedupRule` → new in-memory store: **dedup could never fire** in the API without Redis | same webhook twice → analyzed twice | process-wide store; `test_repeated_finding_adds_no_duplicate_row` |
| B12 | `core/persistence/store.py:153,210` | list/stats returned every row, so a re-observed id appeared several times and was counted several times | duplicate rows in the list | one row per id (latest decision) in all views; `test_list_shows_one_row_per_finding` |
| B13 | `core/credential_broker/broker.py:12` | ignored the manifest's `token_env` and always read `<NAME>_TOKEN` | — | honors `token_env`; `test_broker_honors_manifest_token_env` |
| B14 | `core/manifest/loader.py:8` | `open(path)` uses the platform encoding (cp1252 on Windows, UTF-8 on Linux) | a manifest saved on one OS failed on the other — this happened during this session (see §7) | explicit UTF-8; `test_manifest_loads_as_utf8_regardless_of_platform_encoding` |
| B15 | `core/scanner.py:159,212` | `CKV_K8S_28` regex `NET_ADMIN\|SYS_ADMIN\|ALL` run with `IGNORECASE` flagged any line containing "all" (and `drop: [ALL]`, the recommended hardening) | false positives on ConfigMaps/comments | only capabilities under `add:`; `test_cap_check_*` |
| B16 | `core/scanner.py:167` | missing-liveness-probe / resource-limit checks fired on every YAML file (CI configs, compose, ConfigMaps) | noise in every scan | workload kinds only; `test_probe_check_only_for_workloads` |
| B17 | `api/routes/events.py:38` | invalid webhook JSON → unhandled 500 | `curl -d '{bad'` → 500 | 400; `test_webhook_bad_json_is_400` |
| B18 | `api/routes/events.py:43,45` | missing commit → invented finding id `webhook-001` / artifact `unknown` | fabricated data in the store | payload without a commit is ignored with a reason; `test_webhook_without_commit_is_ignored_not_invented` |
| B19 | `api/routes/events.py:58,72` + `api/main.py` | `/events/demo` was **public** (runs the pipeline and writes the DB with no key) and took any severity string | `?severity=BOGUS` stored a BOGUS finding | key-protected, `Literal` severity; `test_demo_requires_key_when_enforced`, `test_demo_rejects_unknown_severity` |
| B20 | `api/routes/findings.py:50`, `audit.py:10` | unvalidated `limit`/`severity`/`path` query params; no response schemas | — | `Query` bounds, `Literal`s, response models; `test_findings_limit_validated` |
| B21 | `api/main.py` | unhandled errors returned plain-text 500 without the request id | — | JSON 500 with `request_id`; `test_unhandled_error_is_json_with_request_id` |
| B22 | `api/routes/agents.py:27` | agent status was a hardcoded set (`_ACTIVE`), "planned" declared rather than derived | — | status from a live probe (active/blocked + reason) |
| B23 | `core/scanner.py:92,195,386` | all three scanners used `Path(target).rglob(...)`, which yields nothing when the target is a **file** — every finding whose artifact is one file (all webhook findings) was reported "No violations found" | found in the final live check: the demo on `tests/fixtures/terraform/main.tf` (wildcard IAM) came back clean | `_collect()` accepts a file or a directory; `test_scanners_accept_a_single_file_target`, `test_source_scanner_single_file` |

### CLI

| # | Location | Bug | Fix + test |
|---|---|---|---|
| C1 | `concord_cli/main.py:97-99,127-128,…` | every HTTP error (401, 404, 409, 422) printed "Cannot reach API" with exit 2 | exit 1 with the API's reason; `test_http_error_is_not_reported_as_unreachable`, `test_reject_conflict_exit_code` |
| C2 | `concord_cli/main.py:332` | `healthy` computed with `for _, ok, _ in checks if _ != ...` — `_` is rebound to the detail string, so the filter compared the wrong value | `test_diagnostics_healthy_ignores_optional_checks` |
| C3 | — | no way to trigger a scan or inspect one finding from the CLI | `scan`, `scan-status`, `finding <id>` commands; tests added |
| C4 | `concord_cli/main.py` | finding text rendered as Rich markup (a `[red]` in an id changed the output) | `rich.markup.escape` everywhere |

### Dashboard (`api/templates/dashboard.html`)

| # | Line | Bug |
|---|---|---|
| D1 | 445 | `new Date(ts+'Z')` on timestamps that already end in `+00:00` → Invalid Date. Reproduced with node: `old ago(): NaNh`. |
| D2 | 590 | malformed markup: `<span class="kv-v <span class="${resClass}">` |
| D3 | 265-284 | agent list hardcoded in HTML (always showed 3 active / 2 planned) |
| D4 | 536-546, 571-632 | finding fields injected into `innerHTML` unescaped (XSS from a crafted webhook commit message or repo name) |
| D5 | 643-661 | approval never checked `r.ok`: a 400/409 showed a success toast and mutated local state |
| D6 | 924, 947 | detail panel rebuilt every 2 s → lost scroll position and in-progress clicks |
| D7 | 463, 473 | no API-key support: with `CONCORD_API_KEY` set every view showed "Cannot reach API" |
| D8 | 489, 526-530 | "real" findings identified by hardcoded repo name `crms-devops/crms` |
| D9 | 580 | `r.infra_violations\|\|'—'` rendered 0 violations as "—" |
| D10 | 802-834, 909-936 | views counted from different requests at different times (sidebar vs overview vs badge could disagree) |

All replaced by a rebuilt dashboard (see CHANGELOG); verified live in §6.

### Tests

| # | Location | Problem |
|---|---|---|
| T1 | `tests/integration/test_observability.py:152,193`, `tests/integration/test_persistence.py:114` | ids built with `id(object())` — CPython reuses the address of short-lived objects, so "distinct" findings shared an id. Hidden until list views became one-row-per-id. Fixed to enumerate; assertions unchanged. |
| T2 | `tests/integration/test_e2e.py` | placeholder `pass` — the Friday gate tested nothing. Replaced with a real webhook → agents → approval → dedup flow. |

## 5. Test gaps at baseline (now covered)

- Scan route: zero tests → clone, idempotent re-scan, clone failure, concurrency.
- Webhook: only the auth bypass was tested → bad JSON, missing commit, e2e.
- K8s scanner checks: untested → capability and workload-kind tests.
- Orchestrator failure modes (agent crash, no agents): untested → covered.
- kagent / HolmesGPT clients: nothing existed → contract tests against a real MCP SDK server and a HolmesGPT-shaped REST app (`tests/integration/test_remote_agents.py`).

## 6. Live verification performed

API started with `uvicorn api.main:app` on a scratch SQLite DB:

- Dashboard "Scan crms-devops/crms" → real clone of `github.com/crms-devops/crms` at commit `9ce9781fda5d`; 10 violations (terraform 2, kubernetes 8, source 0); tiebreak raised; sidebar, tab badge, list and detail agree.
- Approve from the Approvals view → toast "Approved. (Set GITHUB_TOKEN to also open a GitHub issue.)", queue empty, audit `human_approved:infra`.
- `concord scan` again → "Commit 9ce9781fda5d already analyzed; no new finding.", audit `rescan_unchanged:9ce9781fda5d`, still 1 finding.
- Every endpoint the dashboard uses returned 200 (log in `docs/PROJECT_COMPLETION.md`).

## 7. Issues introduced and caught during this session

- `connectors/tools.yaml` was written in cp1252 by a patch run under the
  system Python (commit `e9ac126`). It loaded on Windows only because of B14.
  Found by a repo-wide UTF-8 scan, converted in `04cd482`, and now guarded by
  `test_repo_manifest_is_valid_utf8`.

## 8. Open items (not fixed — need a decision)

- **Arbitration candidates include "clean" agents.** An agent that found
  nothing (e.g. the source scanner on CRMS: 0 violations) still competes in
  arbitration at `severity × reliability`, so reviewers are offered "approve
  security: No violations found". Excluding zero-violation responses would
  change arbitration outcomes (CLAUDE.md: don't change without discussion).
  The UI shows each candidate's violation count so the reviewer can see it.
- **With the current reliabilities every AI-path finding is a tiebreak**
  (0.92 vs 0.88 → gap 0.04 × severity < 0.15). Auto-resolution only happens
  when a single agent responds.
- TerraSecure / Trivy / Checkov connectors are declared but unused (§3).

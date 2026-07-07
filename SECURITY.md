# Security Policy

## Reporting

Report vulnerabilities via GitHub Security Advisories.
Do not open public issues for security vulnerabilities.

## Threat Model

See docs/threat-model.md for the full threat model.

## Design Commitments

- No master credential. Per-connector scoped tokens only.
- Rollback recommendations always require human approval.
- Every action (including fast-path) logged to audit trail.
- Tool output sanitized before LLM context injection (Phase 3).

# Concord Threat Model

## Threat 1: Prompt Injection via Tool Output

Scanner result contains embedded LLM instructions.
Mitigation (Nov 2026): tool output sanitization in core/orchestrator/context.py.

## Threat 2: Credential Leakage Between Agents

A misconfigured agent exposes its token to another agent context.
Mitigation: credential broker issues per-connector scoped tokens.
No agent holds another agent token. No master credential exists.

## Threat 3: Hallucinated Destructive Action

LLM recommends rollback without human review.
Mitigation: rollback recommendations always gated on human PR approval.
Fix suggestions (non-destructive) may be automated.

## Threat 4: Overconfident Auto-Resolution

LLM self-reports high confidence on a wrong answer, bypassing human review.
Mitigation: confidence = severity_weight * source_reliability.
Empirically calibrated. Not LLM-reported.

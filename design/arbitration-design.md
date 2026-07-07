# Arbitration Layer Design

## Core decision: severity * reliability, not LLM self-report

Literature basis:
Self-reported LLM confidence is poorly calibrated for disagreement cases.
(Ref: DiscoUQ and related position paper cited in Concord IEEE base paper)

## Formula

    confidence_score = severity_weight[severity] * source_reliability[agent]

Severity weights:
    CRITICAL  1.0
    HIGH      0.8
    MEDIUM    0.5
    LOW       0.2

Source reliability (empirical, updated as false positive rates are measured):
    infra (TerraSecure)   0.92
    cicd (Trivy/Checkov)  0.88
    security (OPA)        0.85
    kubernetes (kagent)   0.82
    observability (HGpt)  0.80

## Auto-resolve threshold

confidence_gap >= 0.15: auto-resolve (clear winner)
confidence_gap <  0.15: human tiebreak (post to PR)

## Human tiebreak format

> Concord: Two agents disagree on finding #42.
> Infra agent (0.736): Terraform IAM policy too permissive
> CI/CD agent (0.704): vulnerable base image
> Reply /approve infra or /approve cicd to resolve.

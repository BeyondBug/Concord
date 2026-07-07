# CI/CD Agent

Owner: rj-karan  Phase: 2B  Backing tools: Trivy + Checkov

Trivy and Checkov are already in CRMS GitHub Actions pipeline.
This agent wraps them as MCP connectors for programmatic orchestration.

Source reliability: 0.88 (Trivy + Checkov combined calibration)

Friday demo target (Aug 2026):
CRMS push routes to CICDAgent → Trivy finding → AgentResponse with score.

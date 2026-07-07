# CI/CD Agent

Owner: rj-karan  Phase: 2B  Backing: Trivy + Checkov

Trivy and Checkov already run in CRMS GitHub Actions pipeline.
This wraps them as MCP connectors for programmatic orchestration.

Friday demo (Aug 2026):
  CRMS push routes to CICDAgent
  Trivy finding processed → AgentResponse with confidence_score printed

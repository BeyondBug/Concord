# Infra / Terraform Agent

Assigned: Jash  Phase: 2A  Backing tool: TerraSecure

TerraSecure is already proven: 92.45% accuracy, 0.9230 AUC, SARIF output.
This agent wraps TerraSecure as an MCP connector.

Source reliability: 0.92 (matches TerraSecure ML accuracy)

Friday demo target:
CRMS push triggers TerraSecure scan → InfraAgent.analyze() returns AgentResponse.

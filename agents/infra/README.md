# Infra / Terraform Agent

Owner: Jash  Phase: 2A  Backing: TerraSecure (92.45% acc, SARIF)

Files:
  agent.py         InfraAgent implementation
  terrasecure.py   TerraSecure MCP wrapper
  mcp_server.py    Exposes InfraAgent as an MCP server

Friday demo (Jul-Aug 2026):
  CRMS push triggers TerraSecure scan
  Finding flows through InfraAgent.analyze()
  AgentResponse with confidence_score printed to terminal

Local test:
  pytest tests/integration/test_infra_agent.py -v

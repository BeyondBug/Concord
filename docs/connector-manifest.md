# Connector Manifest Reference (tools.yaml)

The manifest tells Concord which MCP servers are available.
The Tool Registry reads it at startup. No code changes needed to add a tool.

## Schema

    version: "1.0"
    connectors:
      - name: connector-name
        type: mcp
        url: http://host:port
        token_env: ENV_VAR_NAME
        agent: infra
        capabilities:
          - scan_terraform

## Adding a connector

1. Add entry to connectors/tools.yaml
2. Set the token env var in .env
3. Restart the API
4. Write a test in tests/integration/

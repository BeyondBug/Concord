"""
agents/kubernetes/kagent_client.py
Client for kagent's MCP endpoint. kagent is composed here, not rebuilt.

Contract (kagent v0.10.x controller, ``go/core/internal/mcp/mcp_handler.go``):
  endpoint  Streamable HTTP MCP at ``http://<controller>:8083/mcp``
  tools     ``list_agents``  {}                        -> {"agents": [{"ref", "description"}]}
            ``invoke_agent`` {"agent": "ns/name",
                              "task": str,
                              "context_id"?: str}      -> {"agent", "text", "context_id"?}
The controller forwards ``invoke_agent`` to the agent over A2A; the agent (by
default ``kagent/k8s-agent``) answers using its Kubernetes tools and the model
from its ModelConfig.
"""
from __future__ import annotations

from typing import Any

from core.mcp_runtime.mcp_client import MCPSession, tool_text
from core.models.manifest import ConnectorConfig


class KagentClient:
    def __init__(self, connector: ConnectorConfig, transport):
        self.connector = connector
        self._transport = transport

    async def list_agents(self) -> list[dict[str, Any]]:
        async with self._session() as (session, _):
            result = await session.call_tool("list_agents", {})
        structured = result.get("structuredContent") or {}
        agents = structured.get("agents")
        if isinstance(agents, list):
            return agents
        # Older servers only return the text fallback: "ns/name - description".
        text = tool_text(result)
        if not text or text.startswith("No invokable agents"):
            return []
        return [{"ref": line.split(" - ", 1)[0].strip(),
                 "description": line.split(" - ", 1)[1] if " - " in line else ""}
                for line in text.splitlines() if line.strip()]

    async def invoke(self, agent_ref: str, task: str) -> dict[str, Any]:
        """Invoke a kagent agent; returns {"text", "context_id", "server"}."""
        async with self._session() as (session, server_info):
            result = await session.call_tool(
                "invoke_agent", {"agent": agent_ref, "task": task})
        structured = result.get("structuredContent") or {}
        return {
            "text": structured.get("text") or tool_text(result),
            "context_id": structured.get("context_id"),
            "server": server_info,
        }

    def _session(self):
        return _SessionContext(self._transport.get_client_for(self.connector),
                               self.connector.url)


class _SessionContext:
    """Owns the HTTP client and the MCP session for one exchange."""

    def __init__(self, client, url: str):
        self._client = client
        self._session = MCPSession(client, url)

    async def __aenter__(self):
        try:
            await self._session.initialize()
        except BaseException:
            await self._client.aclose()
            raise
        return self._session, self._session.server_info

    async def __aexit__(self, *exc):
        try:
            await self._session.close()
        finally:
            await self._client.aclose()

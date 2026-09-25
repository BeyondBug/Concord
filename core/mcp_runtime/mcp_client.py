"""
core/mcp_runtime/mcp_client.py
Minimal MCP client for the Streamable HTTP transport.

Why not the ``mcp`` SDK client: in mcp 2.x it runs on its own HTTP stack, which
would bypass ``SecureTransport`` — the one place that enforces Concord's TLS
policy and attaches the connector's scoped token. This client speaks the same
wire protocol (JSON-RPC 2.0 over POST, JSON or SSE responses, Mcp-Session-Id)
on top of the ``httpx.AsyncClient`` that SecureTransport builds, and is tested
against a real MCP SDK server in tests/integration/test_mcp_client.py.

Flow per session: ``initialize`` -> ``notifications/initialized`` -> calls ->
best-effort ``DELETE`` to end the session.
"""
from __future__ import annotations

import itertools
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger("concord.mcp")

# Widely supported revision; the server answers with the version it will use.
PROTOCOL_VERSION = "2025-06-18"
_SESSION_HEADER = "mcp-session-id"


class MCPError(RuntimeError):
    """The server answered with a JSON-RPC error, or the reply was unusable."""


class MCPToolError(MCPError):
    """The tool ran but reported failure (``isError: true``)."""


class MCPSession:
    """One MCP session over an already-configured ``httpx.AsyncClient``.

    ``endpoint`` is the full MCP URL (for example ``http://localhost:8083/mcp``).
    The client is borrowed, not owned: the caller closes it.
    """

    def __init__(self, client: httpx.AsyncClient, endpoint: str,
                 client_name: str = "concord"):
        self._client = client
        self._endpoint = endpoint
        self._client_name = client_name
        self._ids = itertools.count(1)
        self._session_id: str | None = None
        self.server_info: dict[str, Any] = {}
        self.protocol_version: str = PROTOCOL_VERSION

    async def __aenter__(self) -> MCPSession:
        await self.initialize()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    # ── Protocol ──────────────────────────────────────────────────────

    async def initialize(self) -> dict[str, Any]:
        result = await self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": self._client_name, "version": "0.1.0"},
        })
        self.server_info = result.get("serverInfo", {})
        self.protocol_version = result.get("protocolVersion", PROTOCOL_VERSION)
        await self._notify("notifications/initialized")
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool and return its result.

        Raises MCPToolError when the tool reports ``isError``.
        """
        result = await self._request("tools/call",
                                     {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise MCPToolError(f"tool '{name}' failed: {tool_text(result)[:500]}")
        return result

    async def close(self) -> None:
        if not self._session_id:
            return
        try:
            await self._client.delete(self._endpoint, headers=self._headers())
        except httpx.HTTPError as exc:  # best effort; the server expires sessions
            logger.debug("MCP session close failed: %s", exc)
        self._session_id = None

    # ── Transport ─────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json, text/event-stream",
                   "Content-Type": "application/json",
                   "MCP-Protocol-Version": self.protocol_version}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _notify(self, method: str) -> None:
        resp = await self._client.post(
            self._endpoint, headers=self._headers(),
            content=json.dumps({"jsonrpc": "2.0", "method": method}),
        )
        if resp.status_code >= 400:
            raise MCPError(f"{method} rejected: HTTP {resp.status_code}")

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        req_id = next(self._ids)
        body = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        resp = await self._client.post(self._endpoint, headers=self._headers(),
                                       content=json.dumps(body))
        if resp.status_code >= 400:
            raise MCPError(f"{method} failed: HTTP {resp.status_code} "
                           f"{resp.text[:200]}")
        sid = resp.headers.get(_SESSION_HEADER)
        if sid:
            self._session_id = sid
        message = _extract_response(resp, req_id)
        if "error" in message:
            err = message["error"] or {}
            raise MCPError(f"{method} error {err.get('code')}: {err.get('message')}")
        return message.get("result") or {}


def _extract_response(resp: httpx.Response, req_id: int) -> dict[str, Any]:
    """Pull the JSON-RPC response for ``req_id`` from a JSON or SSE body."""
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for message in _sse_messages(resp.text):
            if isinstance(message, dict) and message.get("id") == req_id:
                return message
        raise MCPError(f"no response for request {req_id} in event stream")
    try:
        message = resp.json()
    except ValueError as exc:
        raise MCPError(f"non-JSON MCP reply ({ctype or 'no content-type'})") from exc
    if isinstance(message, list):  # a JSON-RPC batch
        message = next((m for m in message if m.get("id") == req_id), {})
    if not isinstance(message, dict) or message.get("id") != req_id:
        raise MCPError(f"no response for request {req_id}")
    return message


def _sse_messages(text: str):
    """Yield decoded JSON payloads from an SSE body (events end at a blank line)."""
    data: list[str] = []
    for line in text.splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line.strip() and data:
            try:
                yield json.loads("\n".join(data))
            except ValueError:
                logger.debug("skipping non-JSON SSE event")
            data = []


def tool_text(result: dict[str, Any]) -> str:
    """Concatenate the text blocks of a tool result."""
    parts = [c.get("text", "") for c in result.get("content", [])
             if isinstance(c, dict) and c.get("type") == "text"]
    return "\n".join(p for p in parts if p).strip()

"""
agents/observability/holmesgpt.py
Client for a HolmesGPT server. HolmesGPT is composed here, not rebuilt.

Contract (HolmesGPT ``server.py``; Helm chart ``robusta/holmes``):
  HolmesGPT is a REST service, not an MCP server (it *consumes* MCP servers as
  toolsets). The manifest therefore declares this connector as ``type: http``.
    GET  /healthz                -> 200 when the process is up
    GET  /readyz                 -> 200 when ready to serve
    POST /api/chat {"ask": str, "model"?: str}
                                 -> {"analysis": str, "tool_calls": [...], ...}
"""
from __future__ import annotations

from typing import Any

from core.models.manifest import ConnectorConfig


class HolmesClient:
    def __init__(self, connector: ConnectorConfig, transport):
        self.connector = connector
        self._transport = transport

    async def ready(self) -> dict[str, Any]:
        async with self._transport.get_client_for(self.connector) as client:
            resp = await client.get("/readyz")
            resp.raise_for_status()
            info: dict[str, Any] = {}
            try:
                model = await client.get("/api/model")
                if model.status_code == 200:
                    info["models"] = model.json()
            except Exception:  # noqa: BLE001 - model listing is optional metadata
                pass
            return info

    async def ask(self, question: str, model: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"ask": question}
        if model:
            body["model"] = model
        async with self._transport.get_client_for(self.connector) as client:
            resp = await client.post("/api/chat", json=body)
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict) or "analysis" not in data:
            raise ValueError("HolmesGPT reply has no 'analysis' field")
        return data

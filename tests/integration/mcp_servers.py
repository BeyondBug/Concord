"""
Real protocol servers for client contract tests.

``kagent_like_server`` is an actual MCP server (the official ``mcp`` SDK,
Streamable HTTP) that exposes the same tools and schemas as kagent's
controller (``list_agents``, ``invoke_agent``; see
agents/kubernetes/kagent_client.py). It proves Concord's MCP client speaks the
protocol correctly. It does NOT stand in for verifying kagent itself — that is
recorded separately in docs/AGENTS_SETUP.md.

``holmes_like_app`` is a FastAPI app with HolmesGPT's /readyz and /api/chat
request/response shapes, for the same purpose.
"""
from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def serve(app):
    """Run an ASGI app on a free localhost port in a background thread."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                            lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


class AgentSummary(BaseModel):
    ref: str
    description: str = ""


class ListAgentsOutput(BaseModel):
    agents: list[AgentSummary]


class InvokeAgentOutput(BaseModel):
    agent: str
    text: str
    context_id: str | None = None


def kagent_like_server(ready_agents=("kagent/k8s-agent",), answer=None,
                       fail_invoke=False):
    """An MCP server with kagent's list_agents / invoke_agent contract."""
    from mcp.server.mcpserver import MCPServer

    calls: list[dict] = []
    server = MCPServer("kagent-agents")

    @server.tool(name="list_agents",
                 description="List invokable kagent agents (accepted + deploymentReady)")
    def list_agents() -> ListAgentsOutput:
        return ListAgentsOutput(agents=[AgentSummary(ref=r, description="test")
                                        for r in ready_agents])

    @server.tool(name="invoke_agent", description="Invoke a kagent agent via A2A")
    def invoke_agent(agent: str, task: str, context_id: str | None = None
                     ) -> InvokeAgentOutput:
        calls.append({"agent": agent, "task": task})
        if fail_invoke:
            raise ValueError("Failed to send A2A message: agent not reachable")
        text = answer or ("ROOT CAUSE: pod default/web runs privileged.\n"
                          "FIX: kubectl patch deploy web ...")
        return InvokeAgentOutput(agent=agent, text=text, context_id="ctx-1")

    app = server.streamable_http_app(streamable_http_path="/mcp")
    return app, calls


class _ChatRequest(BaseModel):
    ask: str
    model: str | None = None


def holmes_like_app(analysis="ROOT CAUSE: web-7f9 is CrashLoopBackOff.\n"
                             "FIX: raise memory limit", ready=True):
    app = FastAPI()
    calls: list[dict] = []

    @app.get("/readyz")
    def readyz():
        if not ready:
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail="not ready")
        return {"status": "ok"}

    @app.get("/api/model")
    def model():
        return {"model_name": ["ollama-qwen"]}

    @app.post("/api/chat")
    def chat(req: _ChatRequest):
        calls.append(req.model_dump())
        return {"analysis": analysis, "conversation_history": [],
                "tool_calls": [{"tool_name": "kubectl_get"}]}

    return app, calls

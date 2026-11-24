"""Pydantic schema for the connector manifest (tools.yaml)."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ConnectorTLS(BaseModel):
    """Optional per-connector TLS configuration.

    All fields optional so existing manifests remain valid. When present:
      ca_bundle  — path to a PEM CA bundle used to verify the server cert.
      client_cert / client_key — enable mutual TLS (mTLS); the client
                   presents this certificate to the MCP server.
      verify     — set False only for local development against self-signed
                   endpoints. Defaults to True (verification on).
    """
    ca_bundle: str | None = None
    client_cert: str | None = None
    client_key: str | None = None
    verify: bool = True


class ConnectorConfig(BaseModel):
    name: str
    type: Literal["mcp", "http"] = "mcp"   # mcp = Streamable HTTP MCP; http = REST
    url: str
    # bearer: send the scoped token from ``token_env``. none: the endpoint has
    # no auth of its own (e.g. a port-forwarded in-cluster service); no token
    # is read or sent.
    auth: Literal["bearer", "none"] = "bearer"
    token_env: str | None = None
    agent: str
    capabilities: list[str]
    timeout_seconds: float = Field(default=30.0, gt=0, le=900)
    tls: ConnectorTLS | None = None

    @model_validator(mode="after")
    def _bearer_needs_token_env(self):
        if self.auth == "bearer" and not self.token_env:
            raise ValueError(f"connector '{self.name}': auth=bearer requires token_env")
        return self


class ManifestConfig(BaseModel):
    version: str
    connectors: list[ConnectorConfig]

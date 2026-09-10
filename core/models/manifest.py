"""Pydantic schema for the connector manifest (tools.yaml)."""
from pydantic import BaseModel


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
    type: str = "mcp"
    url: str
    token_env: str
    agent: str
    capabilities: list[str]
    tls: ConnectorTLS | None = None


class ManifestConfig(BaseModel):
    version: str
    connectors: list[ConnectorConfig]
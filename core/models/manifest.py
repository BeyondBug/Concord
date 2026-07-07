"""Pydantic schema for the connector manifest (tools.yaml)."""
from pydantic import BaseModel


class ConnectorConfig(BaseModel):
    name: str
    type: str = "mcp"
    url: str
    token_env: str
    agent: str
    capabilities: list[str]


class ManifestConfig(BaseModel):
    version: str
    connectors: list[ConnectorConfig]

"""Secure Transport — authenticated connections to MCP servers."""
import httpx
from core.credential_broker import CredentialBroker


class SecureTransport:
    def __init__(self, broker: CredentialBroker):
        self.broker = broker

    def get_client(self, connector_name: str, base_url: str) -> httpx.AsyncClient:
        """Return an authenticated httpx client for one specific connector."""
        token = self.broker.get_token(connector_name)
        return httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
    # TODO Phase 1: add mTLS certificate support

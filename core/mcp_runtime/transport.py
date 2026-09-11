"""
core/mcp_runtime/transport.py
Secure Transport — authenticated, TLS-verified connections to MCP servers.

Security posture (secure by default)
------------------------------------
- TLS certificate verification is ON by default. A per-connector CA bundle
  (``tls.ca_bundle``) can be supplied for private CAs.
- Mutual TLS (mTLS) is supported per connector via ``tls.client_cert`` /
  ``tls.client_key``; the client presents its certificate to the server.
- Plaintext ``http://`` connector URLs are REJECTED unless the operator opts in
  explicitly with ``CONCORD_ALLOW_INSECURE_TRANSPORT=1`` (logged loudly). This
  keeps localhost development working while preventing a plaintext endpoint
  from silently shipping to production.
- The scoped bearer token comes from the credential broker (per-connector, no
  master credential) and is never logged.

Compatibility
-------------
``get_client(name, base_url)`` keeps its original signature. TLS behaviour is
driven by the optional ``ConnectorConfig.tls`` block; pass the connector config
via ``get_client_for(connector)`` to use it, or rely on the URL-scheme guard.
"""
import logging
import os
import ssl

import httpx

from core.credential_broker import CredentialBroker
from core.models.manifest import ConnectorConfig, ConnectorTLS

logger = logging.getLogger("concord.transport")

_INSECURE_ENV = "CONCORD_ALLOW_INSECURE_TRANSPORT"


class InsecureTransportError(RuntimeError):
    """Raised when a plaintext URL is used without the explicit opt-in."""


def _insecure_allowed() -> bool:
    return os.getenv(_INSECURE_ENV, "").strip() in ("1", "true", "True", "yes")


def _build_verify(tls: ConnectorTLS | None):
    """Return the value for httpx's ``verify`` argument.

    True (default) verifies against the system trust store. A CA bundle path
    verifies against that bundle. verify=False is only honored when the
    manifest explicitly sets it (self-signed dev endpoints).
    """
    if tls is None:
        return True
    if tls.verify is False:
        logger.warning("TLS verification DISABLED for a connector via manifest "
                       "(tls.verify=false). Do not use in production.")
        return False
    if tls.ca_bundle:
        # httpx accepts an SSLContext or a CA-bundle path string.
        ctx = ssl.create_default_context(cafile=tls.ca_bundle)
        return ctx
    return True


def _build_cert(tls: ConnectorTLS | None):
    """Return the httpx ``cert`` argument for mTLS, or None."""
    if tls and tls.client_cert:
        if tls.client_key:
            return (tls.client_cert, tls.client_key)
        return tls.client_cert
    return None


class SecureTransport:
    def __init__(self, broker: CredentialBroker):
        self.broker = broker

    def _guard_scheme(self, connector_name: str, base_url: str,
                      tls: ConnectorTLS | None) -> None:
        url = base_url.lower()
        if url.startswith("https://"):
            return
        if url.startswith("http://"):
            if _insecure_allowed():
                logger.warning(
                    "Connector '%s' uses plaintext HTTP (%s). Allowed only "
                    "because %s is set. Traffic is unencrypted.",
                    connector_name, base_url, _INSECURE_ENV,
                )
                return
            raise InsecureTransportError(
                f"Connector '{connector_name}' uses plaintext URL '{base_url}'. "
                f"Use https:// or set {_INSECURE_ENV}=1 to allow (dev only)."
            )
        # Unknown / relative scheme — refuse rather than guess.
        raise InsecureTransportError(
            f"Connector '{connector_name}' has an unsupported URL scheme: "
            f"'{base_url}'. Expected https:// (or http:// with {_INSECURE_ENV}=1)."
        )

    def get_client(self, connector_name: str, base_url: str,
                   tls: ConnectorTLS | None = None) -> httpx.AsyncClient:
        """Return an authenticated, TLS-verified client for one connector."""
        self._guard_scheme(connector_name, base_url, tls)
        token = self.broker.get_token(connector_name)
        return httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
            verify=_build_verify(tls),
            cert=_build_cert(tls),
        )

    def get_client_for(self, connector: ConnectorConfig) -> httpx.AsyncClient:
        """Convenience: build a client straight from a manifest connector."""
        return self.get_client(connector.name, connector.url, connector.tls)
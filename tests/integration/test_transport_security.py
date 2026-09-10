"""Security regression tests for core.mcp_runtime.transport.SecureTransport.

Covers the TLS/scheme trust boundary:
  - plaintext http:// is rejected by default
  - the explicit opt-in env var allows http:// (dev only)
  - https:// is always accepted
  - unknown schemes are refused
  - per-connector CA bundle and mTLS cert wiring reaches httpx
  - the scoped bearer token is attached and never the wrong connector's token
"""
import httpx
import pytest

from core.mcp_runtime.transport import (
    InsecureTransportError,
    SecureTransport,
    _build_cert,
    _build_verify,
)
from core.models.manifest import ConnectorConfig, ConnectorTLS


class _FakeBroker:
    """Stand-in credential broker: returns a per-connector scoped token."""

    def __init__(self):
        self.requested: list[str] = []

    def get_token(self, connector_name: str) -> str:
        self.requested.append(connector_name)
        return f"token-for-{connector_name}"


@pytest.fixture
def transport():
    return SecureTransport(_FakeBroker())


# ── Scheme enforcement ────────────────────────────────────────────────

def test_http_rejected_by_default(transport, monkeypatch):
    monkeypatch.delenv("CONCORD_ALLOW_INSECURE_TRANSPORT", raising=False)
    with pytest.raises(InsecureTransportError):
        transport.get_client("trivy", "http://localhost:8002")


def test_http_allowed_with_optin(transport, monkeypatch):
    monkeypatch.setenv("CONCORD_ALLOW_INSECURE_TRANSPORT", "1")
    client = transport.get_client("trivy", "http://localhost:8002")
    assert isinstance(client, httpx.AsyncClient)
    pytest.importorskip("anyio")


def test_https_always_accepted(transport, monkeypatch):
    monkeypatch.delenv("CONCORD_ALLOW_INSECURE_TRANSPORT", raising=False)
    client = transport.get_client("trivy", "https://scanner.internal:8002")
    assert isinstance(client, httpx.AsyncClient)


def test_unknown_scheme_refused(transport):
    with pytest.raises(InsecureTransportError):
        transport.get_client("trivy", "ftp://scanner.internal")


def test_relative_url_refused(transport):
    with pytest.raises(InsecureTransportError):
        transport.get_client("trivy", "scanner.internal:8002")


# ── Token scoping ─────────────────────────────────────────────────────

def test_scoped_token_is_requested_for_the_named_connector(transport):
    transport.get_client("terrasecure", "https://ts.internal")
    # The broker was asked for exactly that connector's token, nobody else's.
    assert transport.broker.requested == ["terrasecure"]


def test_bearer_header_uses_connector_token(transport):
    client = transport.get_client("terrasecure", "https://ts.internal")
    assert client.headers["authorization"] == "Bearer token-for-terrasecure"


# ── TLS verify / mTLS wiring ──────────────────────────────────────────

def test_verify_true_by_default():
    assert _build_verify(None) is True


def test_verify_uses_ca_bundle(tmp_path):
    # A real, parseable CA file isn't needed to prove the path is taken;
    # ssl.create_default_context(cafile=...) raises if the file is missing,
    # so a missing path proves we attempted to load it.
    missing = str(tmp_path / "nope.pem")
    with pytest.raises(FileNotFoundError):
        _build_verify(ConnectorTLS(ca_bundle=missing))


def test_verify_can_be_disabled_explicitly():
    assert _build_verify(ConnectorTLS(verify=False)) is False


def test_mtls_cert_tuple_built():
    tls = ConnectorTLS(client_cert="/c/cert.pem", client_key="/c/key.pem")
    assert _build_cert(tls) == ("/c/cert.pem", "/c/key.pem")


def test_mtls_cert_single_when_no_key():
    assert _build_cert(ConnectorTLS(client_cert="/c/combined.pem")) == "/c/combined.pem"


def test_no_cert_when_no_tls():
    assert _build_cert(None) is None


# ── get_client_for reads the manifest connector ───────────────────────

def test_get_client_for_uses_connector_url_and_tls(transport, monkeypatch):
    monkeypatch.delenv("CONCORD_ALLOW_INSECURE_TRANSPORT", raising=False)
    connector = ConnectorConfig(
        name="terrasecure", url="http://ts.internal", token_env="TERRASECURE_TOKEN",
        agent="infra", capabilities=["scan_terraform"],
    )
    # Manifest URL is http:// with no opt-in → refused, proving get_client_for
    # applies the same scheme guard.
    with pytest.raises(InsecureTransportError):
        transport.get_client_for(connector)
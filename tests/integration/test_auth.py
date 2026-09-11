"""Tests for api.middleware.auth and the public/protected route boundary.

Covers open dev mode (no key configured) and enforced mode (key configured),
including missing-key, wrong-key, X-API-Key header, and that genuinely public
routes stay reachable either way.
"""
import importlib

import pytest
from fastapi.testclient import TestClient


def _fresh_app(monkeypatch, api_key: str | None):
    """Reload auth + app so the module-level key state is re-read."""
    if api_key is None:
        monkeypatch.delenv("CONCORD_API_KEY", raising=False)
    else:
        monkeypatch.setenv("CONCORD_API_KEY", api_key)
    import api.main as main_mod
    import api.middleware.auth as auth_mod
    importlib.reload(auth_mod)   # reload auth first; main imports from it
    importlib.reload(main_mod)
    return main_mod.app


# ── Open dev mode (no key configured) ─────────────────────────────────

def test_health_public_in_dev_mode(monkeypatch):
    app = _fresh_app(monkeypatch, None)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["auth_enforced"] is False


def test_protected_route_open_in_dev_mode(monkeypatch):
    app = _fresh_app(monkeypatch, None)
    client = TestClient(app)
    # No Authorization header, but dev mode allows it.
    assert client.get("/findings/").status_code == 200


# ── Enforced mode (key configured) ────────────────────────────────────

def test_health_reports_enforced(monkeypatch):
    app = _fresh_app(monkeypatch, "secret-key-123")
    client = TestClient(app)
    assert client.get("/health").json()["auth_enforced"] is True


def test_protected_route_rejects_without_key(monkeypatch):
    app = _fresh_app(monkeypatch, "secret-key-123")
    client = TestClient(app)
    r = client.get("/findings/")
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


def test_protected_route_rejects_wrong_key(monkeypatch):
    app = _fresh_app(monkeypatch, "secret-key-123")
    client = TestClient(app)
    r = client.get("/findings/", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_protected_route_accepts_bearer_key(monkeypatch):
    app = _fresh_app(monkeypatch, "secret-key-123")
    client = TestClient(app)
    r = client.get("/findings/",
                   headers={"Authorization": "Bearer secret-key-123"})
    assert r.status_code == 200


def test_protected_route_accepts_x_api_key(monkeypatch):
    app = _fresh_app(monkeypatch, "secret-key-123")
    client = TestClient(app)
    r = client.get("/findings/", headers={"X-API-Key": "secret-key-123"})
    assert r.status_code == 200


def test_audit_route_protected(monkeypatch):
    app = _fresh_app(monkeypatch, "secret-key-123")
    client = TestClient(app)
    assert client.get("/audit/").status_code == 401
    assert client.get(
        "/audit/", headers={"X-API-Key": "secret-key-123"}
    ).status_code == 200


# ── Public routes stay open even when auth is enforced ────────────────

def test_health_public_when_enforced(monkeypatch):
    app = _fresh_app(monkeypatch, "secret-key-123")
    client = TestClient(app)
    assert client.get("/health").status_code == 200


def test_webhook_stays_key_free_when_enforced(monkeypatch):
    """The GitHub webhook uses its own HMAC check, not the API key.

    With no WEBHOOK_SECRET set it runs in dev mode and accepts the payload, so
    a 401 here would mean the API key wrongly guarded it.
    """
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    app = _fresh_app(monkeypatch, "secret-key-123")
    client = TestClient(app)
    r = client.post("/events/github", json={"repository": {"full_name": "a/b"}})
    assert r.status_code != 401


def test_correlation_id_header_present(monkeypatch):
    app = _fresh_app(monkeypatch, None)
    client = TestClient(app)
    r = client.get("/health")
    assert r.headers.get("X-Request-ID")


@pytest.fixture(autouse=True)
def _restore_app(monkeypatch):
    """Reload app back to a clean default after each test."""
    yield
    monkeypatch.delenv("CONCORD_API_KEY", raising=False)
    import api.main as main_mod
    import api.middleware.auth as auth_mod
    importlib.reload(auth_mod)
    importlib.reload(main_mod)
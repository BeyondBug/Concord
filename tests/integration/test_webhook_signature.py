"""Issue #52: the webhook fails closed and the app will not start without a secret."""
import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import github_signature

PUSH = {"repository": {"full_name": "a/b"}}


@pytest.fixture
def client():
    from api.main import app
    with TestClient(app) as c:
        yield c


def test_unsigned_webhook_is_401(client):
    assert client.post("/events/github", json=PUSH).status_code == 401


def test_wrong_signature_is_401(client):
    body = json.dumps(PUSH).encode()
    r = client.post("/events/github", content=body, headers={
        "X-Hub-Signature-256": github_signature(body, "some-other-secret")})
    assert r.status_code == 401


def test_signed_webhook_is_accepted(client, post_github):
    assert post_github(client, PUSH).status_code == 202


@pytest.mark.parametrize("value", [None, "", "  ", "changeme"])
def test_startup_fails_without_real_secret(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("WEBHOOK_SECRET")
    else:
        monkeypatch.setenv("WEBHOOK_SECRET", value)
    from api.main import app
    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"), TestClient(app):
        pass


@pytest.mark.parametrize("value", ["", "changeme"])
def test_request_is_rejected_even_if_secret_removed_after_start(client, monkeypatch, value):
    monkeypatch.setenv("WEBHOOK_SECRET", value)
    body = json.dumps(PUSH).encode()
    r = client.post("/events/github", content=body, headers={
        "X-Hub-Signature-256": github_signature(body, value or "x")})
    assert r.status_code == 401

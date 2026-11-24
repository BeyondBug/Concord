"""Issue #105: IDs and agent names from the URL are validated before they are logged."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("CONCORD_API_KEY", raising=False)
    from api.main import app
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("bad", ["a%0Afake-log-line", "a%0D", "a b", "a;b", "%E2%80%AE"])
def test_unsafe_finding_id_is_422(client, bad):
    assert client.post(f"/events/findings/{bad}/approve/infra").status_code == 422
    assert client.post(f"/events/findings/{bad}/reject").status_code == 422
    assert client.get(f"/findings/{bad}").status_code == 422


def test_unsafe_agent_is_422(client):
    assert client.post("/events/findings/GH-1/approve/inf%0Ara").status_code == 422


def test_normal_ids_still_reach_the_handler(client):
    # 404 (not 422) proves the pattern accepts the real ID shapes.
    for fid in ["GH-0123456789ab", "DEMO-IAM-CRITICAL", "CRMS-20261124-101500", "CVE-2024-1.2:3"]:
        assert client.get(f"/findings/{fid}").status_code == 404

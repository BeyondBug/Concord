"""Issue #53: openapi.yaml is valid, matches the server, and covers every route
the dashboard and CLI call. Fails on any drift between spec and code."""
import re
from pathlib import Path

import pytest
import yaml
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
METHODS = {"get", "post", "put", "patch", "delete"}


def _spec_ops():
    for path, item in SPEC["paths"].items():
        for method, op in item.items():
            if method in METHODS:
                yield path, method, op


def _served():
    from api.main import app
    ops = {(p, m) for p, item in app.openapi()["paths"].items() for m in item}
    # The dashboard route is excluded from FastAPI's generated schema.
    return ops | {("/", "get")}


def test_spec_is_valid_openapi():
    validate(SPEC)


def test_every_operation_declares_status_and_issue():
    for path, method, op in _spec_ops():
        status = op.get("x-concord-status")
        assert status in {"current", "changed", "planned"}, (method, path)
        if status != "current":
            assert isinstance(op.get("x-concord-issue"), int), (method, path)


def test_every_served_route_is_in_the_spec():
    spec = {(p, m) for p, m, op in _spec_ops() if op["x-concord-status"] != "planned"}
    missing = _served() - spec
    assert not missing, f"served but not in openapi.yaml (or marked planned): {missing}"


def test_spec_only_promises_what_is_served():
    served = _served()
    for path, method, op in _spec_ops():
        if op["x-concord-status"] == "planned":
            assert (path, method) not in served, f"{method} {path} is served: mark it current"
        else:
            assert (path, method) in served, f"{method} {path} is in the spec but not served"


def _template_regex(path: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\\{[^/]+?\\}", "[^/]+", re.escape(path)) + "$")


def _client_urls(text: str) -> set[str]:
    """Route literals in the dashboard / CLI, with interpolations as placeholders."""
    urls = set()
    for raw in re.findall(r"['\"`](/(?:findings|events|audit|agents|health|version|jobs|ingest)[^'\"`\s]*)", text):
        path = raw.split("?")[0]
        path = re.sub(r"\$\{[^}]*\}|\{[^}]*\}|\"\s*\+[^+]+\+\s*\"", "X", path)
        urls.add(path)
    return urls


@pytest.mark.parametrize("source", ["api/templates/dashboard.html", "concord_cli/main.py"])
def test_every_route_the_clients_call_is_in_the_spec(source):
    urls = _client_urls((ROOT / source).read_text(encoding="utf-8"))
    assert urls, f"no API calls found in {source}; the extraction regex is stale"
    patterns = [_template_regex(p) for p in SPEC["paths"]]
    uncovered = {u for u in urls if not any(rx.match(u) for rx in patterns)}
    assert not uncovered, f"{source} calls routes missing from openapi.yaml: {uncovered}"


def test_real_responses_match_the_spec_schemas(monkeypatch):
    """What the server returns today must validate against the contract."""
    import jsonschema
    from fastapi.testclient import TestClient

    from api.main import app
    monkeypatch.delenv("CONCORD_API_KEY", raising=False)
    schemas = SPEC["components"]["schemas"]

    def check(name, instance):
        v = jsonschema.Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": {"schemas": schemas}})
        errors = [f"{list(e.path)}: {e.message}" for e in v.iter_errors(instance)]
        assert not errors, f"{name}: {errors[:3]}"

    with TestClient(app) as c:
        for sev in ["CRITICAL", "LOW"]:
            check("AnalysisResult", c.post("/events/demo", params={"severity": sev}).json())
        check("FindingList", c.get("/findings/").json())
        check("FindingDetail", c.get("/findings/DEMO-IAM-CRITICAL/detail").json())
        check("AgentList", c.get("/agents/").json())
        check("Health", c.get("/health").json())
        check("ScanState", c.get("/events/scan-status").json())
        for entry in c.get("/audit/").json()["entries"]:
            check("AuditEntry", entry)

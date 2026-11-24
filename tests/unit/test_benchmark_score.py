"""Issue #54: the benchmark scorer buckets every result exactly once."""
import json
import re
from pathlib import Path

import jsonschema
import pytest
import yaml

from benchmark.score import Result, read_sarif, score

ROOT = Path(__file__).resolve().parents[2] / "benchmark"
VULN = {"name": "demo", "kind": "vulnerable"}
CLEAN = {"name": "clean-demo", "kind": "clean"}
RULEMAP = {"checkov": {"CKV_1": "s3-public-acl", "CKV_2": "iam-wildcard"}}
LABELS = {
    "repo": "demo",
    "scope": ["infra/"],
    "findings": [
        {"id": "DEMO-001", "class": "s3-public-acl", "file": "infra/s3.tf",
         "start_line": 10, "end_line": 14, "severity": "HIGH", "why": "bucket ACL is public-read"},
        {"id": "DEMO-002", "class": "iam-wildcard", "file": "infra/iam.tf",
         "start_line": 3, "end_line": 8, "severity": "CRITICAL", "why": "policy allows * on *"},
    ],
    "rejected": [
        {"class": "s3-public-acl", "file": "infra/site.tf", "start_line": 1, "end_line": 5,
         "reason": "static website bucket that is meant to be public"},
    ],
}


def r(rule, file, line, tool="checkov"):
    return Result(tool, rule, file, line)


def test_every_bucket():
    s = score(VULN, LABELS, [
        r("CKV_1", "infra/s3.tf", 12),       # tp
        r("CKV_1", "infra/s3.tf", 16),       # duplicate (end_line + 2 slack)
        r("CKV_1", "infra/site.tf", 2),      # fp: reviewed false alarm
        r("CKV_1", "infra/other.tf", 1),     # unreviewed
        r("CKV_9", "infra/s3.tf", 12),       # unmapped rule
        r("CKV_1", "app/s3.tf", 12),         # out of scope
    ], RULEMAP)
    counts = s.summary()["counts"]
    assert counts == {"tp": 1, "duplicate": 1, "fp": 1, "unreviewed": 1,
                      "unmapped": 1, "out_of_scope": 1}
    assert s.summary()["missed"] == ["DEMO-002"]
    assert (s.precision, s.recall) == (0.5, 0.5)


def test_class_and_line_must_both_match():
    s = score(VULN, LABELS, [
        r("CKV_2", "infra/s3.tf", 12),       # right place, wrong class
        r("CKV_1", "infra/s3.tf", 17),       # right class, 3 lines past the range
    ], RULEMAP)
    assert s.tp == 0 and s.summary()["counts"]["unreviewed"] == 2


def test_any_alert_on_a_clean_repo_is_a_false_positive():
    s = score(CLEAN, {"repo": "clean-demo", "scope": [], "findings": [], "rejected": []},
              [r("CKV_1", "main.tf", 4), r("UNKNOWN", "main.tf", 9)], RULEMAP)
    assert s.fp == 2 and s.precision == 0.0 and s.recall is None


def test_no_results_means_zero_recall_not_a_crash():
    s = score(VULN, LABELS, [], RULEMAP)
    assert s.recall == 0.0 and s.precision is None and s.summary()["f1"] is None


def test_read_sarif_normalises_paths(tmp_path):
    log = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "Checkov"}}, "results": [
        {"ruleId": "CKV_1", "locations": [{"physicalLocation": {
            "artifactLocation": {"uri": "file:///work/repo/infra/s3.tf"}, "region": {"startLine": 11}}}]},
        {"ruleId": "CKV_2", "locations": [{"physicalLocation": {
            "artifactLocation": {"uri": "./infra/iam.tf"}, "region": {"startLine": 4}}}]},
        {"ruleId": "CKV_3", "locations": []},
    ]}]}
    p = tmp_path / "out.sarif"
    p.write_text(json.dumps(log))
    assert read_sarif(p, "/work/repo") == [
        Result("checkov", "CKV_1", "infra/s3.tf", 11),
        Result("checkov", "CKV_2", "infra/iam.tf", 4),
    ]


def test_read_sarif_rejects_other_versions(tmp_path):
    p = tmp_path / "old.sarif"
    p.write_text(json.dumps({"version": "1.0.0", "runs": []}))
    with pytest.raises(ValueError, match="2.1.0"):
        read_sarif(p)


def test_demo_labels_match_the_schema():
    schema = json.loads((ROOT / "expected.schema.json").read_text())
    jsonschema.validate(LABELS, schema)


@pytest.mark.parametrize("path", sorted((ROOT / "labels").glob("*.json")), ids=lambda p: p.name)
def test_committed_labels_are_valid_and_consistent(path):
    data = json.loads(path.read_text())
    jsonschema.validate(data, json.loads((ROOT / "expected.schema.json").read_text()))
    ids = [f["id"] for f in data["findings"]]
    assert len(ids) == len(set(ids)), "duplicate label ids"
    for f in data["findings"] + data["rejected"]:
        assert f["start_line"] <= f["end_line"], f


def test_repos_are_pinned_to_full_commits():
    repos = yaml.safe_load((ROOT / "repos.yaml").read_text())["repos"]
    names = [x["name"] for x in repos]
    assert len(names) == len(set(names))
    for x in repos:
        assert x["kind"] in {"vulnerable", "clean"}
        if "url" in x:
            assert re.fullmatch(r"[0-9a-f]{40}", x["commit"]), x["name"]
        else:
            assert (ROOT.parent / x["path"]).is_dir(), x["name"]


def test_hygiene_checks_are_neutral_even_on_clean_repos():
    rulemap = {"checkov": {**RULEMAP["checkov"], "CKV_AWS_18": "hygiene"}}
    s = score(CLEAN, {"repo": "clean-demo", "scope": [], "findings": [], "rejected": []},
              [r("CKV_AWS_18", "main.tf", 4)], rulemap)
    assert s.summary()["counts"] == {"hygiene": 1} and s.fp == 0
    s = score(VULN, LABELS, [r("CKV_AWS_18", "infra/s3.tf", 12)], rulemap)
    assert s.summary()["counts"] == {"hygiene": 1} and s.tp == 0


def test_clean_fixture_scores_clean_with_real_tool_output():
    """Checkov and Trivy SARIF captured from benchmark/fixtures/clean-terraform."""
    from benchmark.score import load_repo, load_rulemap
    results = [r(rule, "main.tf", 1) for rule in
               ["CKV2_AWS_5", "CKV2_AWS_62", "CKV_AWS_144", "CKV_AWS_18", "CKV2_AWS_61"]]
    results += [r(rule, "main.tf", 1, tool="trivy") for rule in ["AWS-0089", "AWS-0132"]]
    s = score(load_repo("clean-terraform"),
              {"repo": "clean-terraform", "scope": [], "findings": [], "rejected": []},
              results, load_rulemap())
    assert s.fp == 0 and s.summary()["counts"] == {"hygiene": 7}

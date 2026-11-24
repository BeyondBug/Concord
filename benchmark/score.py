"""Score any scanner's SARIF output against the benchmark labels.

    python -m benchmark.score --repo terragoat results.sarif [more.sarif ...] [--json]

Matching: a result is a true positive when its file equals a label's file, its
line falls inside the label's range (with LINE_SLACK lines either side), and
its rule maps to the label's class through benchmark/rulemap.yaml. Each label
can be matched once; further hits on it count as duplicates, not errors.

Every result lands in exactly one bucket:
  tp            matches an unmatched true finding
  duplicate     matches a finding that was already matched
  fp            matches a reviewed false alarm, or any alert in a clean repo
  unreviewed    in scope, mapped, but no human has judged it yet
  unmapped      the rule has no class in rulemap.yaml (a mapping gap, shown so it gets fixed)
  hygiene       the rule is mapped to the class "hygiene": a best-practice check (logging,
                replication, lifecycle) rather than a security exposure, so it is neither
                rewarded nor punished
  out_of_scope  outside the reviewed paths
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

HERE = Path(__file__).resolve().parent
LINE_SLACK = 2
HYGIENE = "hygiene"


@dataclass(frozen=True)
class Result:
    tool: str
    rule: str
    file: str
    line: int


@dataclass
class Score:
    repo: str
    kind: str
    buckets: dict[str, list[Result]] = field(default_factory=dict)
    missed: list[dict] = field(default_factory=list)
    by_class: dict[str, Counter] = field(default_factory=dict)

    @property
    def tp(self) -> int:
        return len(self.buckets.get("tp", []))

    @property
    def fp(self) -> int:
        return len(self.buckets.get("fp", []))

    @property
    def fn(self) -> int:
        return len(self.missed)

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    def summary(self) -> dict:
        p, r = self.precision, self.recall
        f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
        return {
            "repo": self.repo, "kind": self.kind,
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": p, "recall": r, "f1": f1,
            "counts": {k: len(v) for k, v in sorted(self.buckets.items())},
            "by_class": {c: dict(v) for c, v in sorted(self.by_class.items())},
            "missed": [m["id"] for m in self.missed],
        }


def load_repo(name: str) -> dict:
    repos = yaml.safe_load((HERE / "repos.yaml").read_text(encoding="utf-8"))["repos"]
    for r in repos:
        if r["name"] == name:
            return r
    raise SystemExit(f"unknown benchmark repo {name!r}")


def load_rulemap(path: Path | None = None) -> dict[str, dict[str, str]]:
    data = yaml.safe_load((path or HERE / "rulemap.yaml").read_text(encoding="utf-8")) or {}
    return {tool.lower(): {str(k): v for k, v in (rules or {}).items()} for tool, rules in data.items()}


def _relative(uri: str, repo_root: str | None) -> str:
    path = unquote(urlparse(uri).path) if "://" in uri else unquote(uri)
    path = path.replace("\\", "/")
    if repo_root:
        root = repo_root.rstrip("/") + "/"
        if path.startswith(root):
            path = path[len(root):]
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def read_sarif(path: Path, repo_root: str | None = None) -> list[Result]:
    """Flatten a SARIF 2.1.0 log into (tool, rule, file, line) results."""
    log = json.loads(path.read_text(encoding="utf-8"))
    if log.get("version") != "2.1.0":
        raise ValueError(f"{path}: not a SARIF 2.1.0 log")
    out = []
    for run in log.get("runs", []):
        tool = run.get("tool", {}).get("driver", {}).get("name", "unknown").lower()
        artifacts = run.get("artifacts", [])
        for res in run.get("results", []):
            for loc in res.get("locations", [])[:1]:
                phys = loc.get("physicalLocation", {})
                art = phys.get("artifactLocation", {})
                uri = art.get("uri")
                if uri is None and isinstance(art.get("index"), int) and 0 <= art["index"] < len(artifacts):
                    # SARIF lets a location point into run.artifacts instead of repeating the URI.
                    uri = artifacts[art["index"]].get("location", {}).get("uri")
                if not uri:
                    continue
                line = phys.get("region", {}).get("startLine", 1)
                out.append(Result(tool, str(res.get("ruleId", "")), _relative(uri, repo_root), int(line)))
    return out


def _hits(label: dict, r: Result, cls: str) -> bool:
    return (label["file"] == r.file and label["class"] == cls
            and label["start_line"] - LINE_SLACK <= r.line <= label["end_line"] + LINE_SLACK)


def _distance(label: dict, line: int) -> int:
    """0 inside the label's range, else how many lines outside it."""
    return max(label["start_line"] - line, 0, line - label["end_line"])


def _best(findings: list[dict], r: Result, cls: str, matched: set[str]) -> dict | None:
    """The eligible label for r: unmatched ones first, then the closest range."""
    eligible = [f for f in findings if _hits(f, r, cls)]
    return min(eligible, key=lambda f: (f["id"] in matched, _distance(f, r.line), f["start_line"]),
               default=None)


def score(repo: dict, expected: dict, results: list[Result], rulemap: dict) -> Score:
    s = Score(repo=repo["name"], kind=repo["kind"])
    matched: set[str] = set()
    scope = expected.get("scope", [])

    def put(bucket: str, r: Result, cls: str | None = None) -> None:
        s.buckets.setdefault(bucket, []).append(r)
        if cls and bucket in ("tp", "fp", "unreviewed"):
            s.by_class.setdefault(cls, Counter())[bucket] += 1

    for r in sorted(results, key=lambda x: (x.file, x.line, x.tool, x.rule)):
        cls = rulemap.get(r.tool, {}).get(r.rule)
        if cls == HYGIENE:
            put("hygiene", r)
            continue
        if repo["kind"] == "clean":
            put("fp", r, cls)  # any alert on a clean repo is noise
            continue
        if scope and not any(r.file.startswith(p) for p in scope):
            put("out_of_scope", r)
            continue
        if cls is None:
            put("unmapped", r)
            continue
        label = _best(expected["findings"], r, cls, matched)
        if label is not None:
            put("duplicate" if label["id"] in matched else "tp", r, cls)
            matched.add(label["id"])
        elif any(_hits(x, r, cls) for x in expected["rejected"]):
            put("fp", r, cls)
        else:
            put("unreviewed", r, cls)

    s.missed = [f for f in expected["findings"] if f["id"] not in matched]
    for f in s.missed:
        s.by_class.setdefault(f["class"], Counter())["fn"] += 1
    return s


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="benchmark repo name from repos.yaml")
    ap.add_argument("sarif", nargs="+", type=Path, help="SARIF 2.1.0 files (one or more tools)")
    ap.add_argument("--root", help="absolute path prefix to strip from result URIs")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    ap.add_argument("--fail-on-unreviewed", action="store_true",
                    help="exit 1 when any in-scope result is unreviewed or its rule is unmapped")
    a = ap.parse_args(argv)

    repo = load_repo(a.repo)
    expected_path = HERE / "labels" / f"{a.repo}.json"
    expected = (json.loads(expected_path.read_text(encoding="utf-8")) if expected_path.exists()
                else {"repo": a.repo, "scope": [], "findings": [], "rejected": []})
    results = [r for p in a.sarif for r in read_sarif(p, a.root)]
    s = score(repo, expected, results, load_rulemap())
    summary = s.summary()

    if a.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{s.repo} ({s.kind}): precision {_fmt(s.precision)}  recall {_fmt(s.recall)}  "
              f"tp {s.tp}  fp {s.fp}  fn {s.fn}")
        print("buckets: " + ", ".join(f"{k} {v}" for k, v in summary["counts"].items()))
    counts = summary["counts"]
    return 1 if a.fail_on_unreviewed and (counts.get("unreviewed") or counts.get("unmapped")) else 0


if __name__ == "__main__":
    sys.exit(main())

"""Fetch the benchmark repositories at their pinned commits.

    python -m benchmark.fetch [--dest .bench]

Each repository is cloned once into <dest>/<name> and checked out at the
commit in repos.yaml. Nothing in the fetched code is executed: scanners only
read the files. In-repo fixtures (entries with `path:`) need no fetching.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def fetch(repo: dict, dest: Path) -> Path:
    target = dest / repo["name"]
    if not (target / ".git").exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--quiet", "--filter=blob:none", "--no-checkout", repo["url"], str(target))
    git("-c", "advice.detachedHead=false", "checkout", "--quiet", repo["commit"], cwd=target)
    head = git("rev-parse", "HEAD", cwd=target)
    if head != repo["commit"]:
        raise SystemExit(f"{repo['name']}: HEAD is {head}, expected {repo['commit']}")
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch benchmark repos at pinned commits")
    ap.add_argument("--dest", type=Path, default=Path(".bench"))
    a = ap.parse_args(argv)
    repos = yaml.safe_load((HERE / "repos.yaml").read_text(encoding="utf-8"))["repos"]
    for r in repos:
        where = fetch(r, a.dest) if "url" in r else Path(r["path"])
        print(f"{r['name']:<16} {r.get('commit', 'in-repo')[:12]:<12} {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

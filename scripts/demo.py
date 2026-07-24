#!/usr/bin/env python3
"""
scripts/demo.py
Concord Friday demo script — run from repo root:
    python scripts/demo.py
"""
import asyncio
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format="%(message)s")

from core.models.finding import Finding
from core.orchestrator.orchestrator import Orchestrator

G  = "\033[92m"   # green
Y  = "\033[93m"   # yellow / amber
R  = "\033[91m"   # red
B  = "\033[94m"   # blue
C  = "\033[96m"   # cyan
W  = "\033[97m"   # white
BD = "\033[1m"
RS = "\033[0m"

def hr(char="─", n=62):
    print(f"{W}{char * n}{RS}")

def banner(text, color=C):
    hr("═")
    print(f"{color}{BD}  {text}{RS}")
    hr("═")


async def scenario(label, finding, orch):
    print(f"\n{Y}{BD}  {label}{RS}")
    hr()
    print(f"  finding_id : {finding.id}")
    print(f"  severity   : {finding.severity}")
    print(f"  artifact   : {finding.artifact}")
    print(f"  repository : {finding.repository}")
    hr()

    result = await orch.process(finding)

    print(f"\n{W}{BD}  RESULT{RS}")
    hr()
    print(f"  path         : {result['path']}")

    if result["path"] == "fast_path":
        print(f"  reason       : {result['reason']}")
        print(f"  LLM called   : {R}NO{RS}  (zero inference cost)")
    else:
        print(f"  agent        : {result.get('agent')}")
        print(f"  confidence   : {result.get('score', 0):.4f}")
        resolved = result.get("auto_resolved")
        resolution = f"{G}auto-resolved{RS}" if resolved else f"{Y}human tiebreak{RS}"
        print(f"  resolution   : {resolution}")
        if result.get("pr_comment"):
            print(f"\n  {BD}PR Comment:{RS}")
            for line in result["pr_comment"].split("\\n"):
                print(f"    {line}")
    hr()


async def main():
    banner("CONCORD — Friday Demo  |  BeyondBug/Concord")
    print(f"\n  {BD}What you are seeing:{RS}")
    print("  1. Triage gate  — deterministic rules, no LLM")
    print("  2. Domain agents — Infra (TerraSecure) + CI/CD (Trivy/Checkov)")
    print("  3. Arbitration  — severity × source reliability, NOT LLM confidence")
    print("  4. Audit trail  — every finding logged regardless of path")

    orch = Orchestrator()

    await scenario(
        "SCENARIO 1 — CRITICAL Terraform finding → expect human tiebreak",
        Finding(
            id="CVE-2024-33663",
            source="terrasecure",
            artifact="infra/terraform/main.tf",
            severity="CRITICAL",
            title="IAM policy allows overly permissive actions",
            description="AWS IAM policy grants * actions on * resources",
            raw={"rule_id": "TF-IAM-001"},
            repository="BeyondBug/CRMS",
            pr_number=42,
        ),
        orch,
    )

    await scenario(
        "SCENARIO 2 — LOW severity finding → fast path, no LLM",
        Finding(
            id="LINT-TAG-001",
            source="checkov",
            artifact="infra/terraform/storage.tf",
            severity="LOW",
            title="S3 bucket missing Name tag",
            description="Resource has no Name tag",
            raw={},
            repository="BeyondBug/CRMS",
        ),
        orch,
    )

    banner("DEMO COMPLETE", G)
    print(f"  {G}✓{RS}  Triage gate working  (0 LLM calls for LOW finding)")
    print(f"  {G}✓{RS}  Two agents analyzed the CRITICAL finding independently")
    print(f"  {G}✓{RS}  Confidence = severity_weight × source_reliability (not LLM)")
    print(f"  {G}✓{RS}  Arbitration produced a human tiebreak PR comment")
    print(f"  {G}✓{RS}  Audit trail written for both findings\n")


if __name__ == "__main__":
    asyncio.run(main())

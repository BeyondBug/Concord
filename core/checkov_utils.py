"""
core/checkov_utils.py
Cross-platform Checkov runner.
Uses stdout→file redirect to avoid Windows CMD pipe issues.
"""
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("concord.checkov")
_TMP = Path("_checkov_out.json")   # temp file in repo root


def find_checkov() -> list:
    exe = shutil.which("checkov")
    if exe:
        return [exe]
    scripts = Path(sys.executable).parent / "Scripts"
    for name in ["checkov.exe", "checkov.CMD", "checkov.cmd", "checkov"]:
        p = scripts / name
        if p.exists():
            return [str(p)]
    local = Path.home() / ".local" / "bin" / "checkov"
    if local.exists():
        return [str(local)]
    return []


def checkov_scan(target: str, framework: str) -> dict:
    """Run a real Checkov scan, return parsed findings dict."""
    cmd = find_checkov()
    if not cmd:
        return _err("Checkov not found. Run: pip install checkov")

    p = Path(target)
    if not p.exists():
        return _err(f"Target not found: {target}")

    run_cmd = (cmd +
               ["-f" if p.is_file() else "-d", str(p),
                "--framework", framework,
                "--output", "json"])

    logger.info("checkov -d %s --framework %s", target, framework)

    try:
        # Write stdout directly to a file — avoids Windows CMD pipe problems
        with open(_TMP, "w", encoding="utf-8") as fout:
            result = subprocess.run(
                run_cmd,
                stdout=fout,
                stderr=subprocess.PIPE,
                timeout=180,
            )
    except subprocess.TimeoutExpired:
        _TMP.unlink(missing_ok=True)
        return _err("Checkov timed out.")
    except Exception as exc:
        _TMP.unlink(missing_ok=True)
        return _err(f"Checkov error: {exc}")

    # Read the file back
    if not _TMP.exists() or _TMP.stat().st_size == 0:
        _TMP.unlink(missing_ok=True)
        stderr_msg = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        logger.warning("Checkov empty output. stderr: %s", stderr_msg[:300])
        return _err(f"Checkov produced no output (rc={result.returncode}).")

    raw = _TMP.read_text(encoding="utf-8", errors="replace").strip()
    _TMP.unlink(missing_ok=True)

    data = _load_json(raw)
    if data is None:
        logger.warning("Checkov output not JSON. First 300 chars: %s", raw[:300])
        return _err("Checkov output could not be parsed as JSON.")

    return _parse(data, target)


def _load_json(raw: str):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Checkov sometimes prepends a progress bar line — try each line
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith(("[", "{")):
            try:
                return json.loads(line)
            except Exception:
                continue
    return None


def _parse(data, target: str) -> dict:
    results_list = data if isinstance(data, list) else [data]
    failed, passed = [], 0

    for res in results_list:
        if not isinstance(res, dict):
            continue
        r = res.get("results", res)
        if isinstance(r, dict):
            failed.extend(r.get("failed_checks", []))
            passed += len(r.get("passed_checks", []))

    if not failed:
        return {"total": 0, "passed": passed, "checks": [],
                "root_cause": f"No violations found in {target}. {passed} checks passed.",
                "fix": "Configuration is compliant."}

    lines = []
    for c in failed[:5]:
        fp = c.get("file_path", "")
        ln = c.get("file_line_range", [])
        loc = f":{ln[0]}" if ln else ""
        lines.append(
            f"  [{c.get('check_id','?')}] "
            f"{c.get('check_name','')} — "
            f"{c.get('resource','')} "
            f"({Path(fp).name}{loc})"
        )

    top      = failed[0]
    cid      = top.get("check_id", "CKV_UNKNOWN")
    name     = top.get("check_name", "")
    resource = top.get("resource", "")
    guideline = top.get("guideline", "")
    fp       = top.get("file_path", "")
    ln       = top.get("file_line_range", [])
    loc      = f" ({Path(fp).name}:{ln[0]})" if fp and ln else ""

    return {
        "total":      len(failed),
        "passed":     passed,
        "checks":     failed[:5],
        "root_cause": (f"[{cid}] {name}{loc}.\n"
                       f"{len(failed)} violation(s) found:\n" +
                       "\n".join(lines)),
        "fix":        (f"Fix {cid} in '{resource}'.\n"
                       f"{guideline or 'Apply security best practices.'}"),
    }


def _err(msg: str) -> dict:
    return {"total": 0, "passed": 0, "checks": [],
            "root_cause": msg, "fix": ""}

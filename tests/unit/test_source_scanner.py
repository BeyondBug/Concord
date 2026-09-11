"""Unit tests for core.scanner.SourceCodeScanner (backs SecurityPolicyAgent)."""
from pathlib import Path

from core.scanner import SourceCodeScanner, scan_to_dict


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_detects_python_eval(tmp_path):
    _write(tmp_path, "bad.py", "x = eval(user_input)\n")
    findings = SourceCodeScanner().scan(str(tmp_path))
    assert any(f.check_id == "CONCORD_PY_EXEC" for f in findings)
    assert all(f.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"} for f in findings)


def test_detects_shell_true(tmp_path):
    _write(tmp_path, "run.py",
           "import subprocess\nsubprocess.run(cmd, shell=True)\n")
    findings = SourceCodeScanner().scan(str(tmp_path))
    assert any(f.check_id == "CONCORD_SHELL_TRUE" for f in findings)


def test_detects_hardcoded_secret_any_language(tmp_path):
    _write(tmp_path, "conf.js", 'const apiKey = "abcdef123456";\n')
    findings = SourceCodeScanner().scan(str(tmp_path))
    assert any(f.check_id == "CONCORD_SECRET" for f in findings)


def test_language_scoping_php_sink_not_flagged_in_python(tmp_path):
    # `system(` in a .py file must NOT trigger the PHP-only sink.
    _write(tmp_path, "ok.py", "def system(x):\n    return x\n")
    findings = SourceCodeScanner().scan(str(tmp_path))
    assert not any(f.check_id == "CONCORD_PHP_EXEC" for f in findings)


def test_clean_code_returns_no_findings(tmp_path):
    _write(tmp_path, "clean.py", "def add(a, b):\n    return a + b\n")
    findings = SourceCodeScanner().scan(str(tmp_path))
    assert findings == []


def test_skips_vendored_directories(tmp_path):
    vendor = tmp_path / "node_modules"
    vendor.mkdir()
    (vendor / "evil.js").write_text("eval(x)\n", encoding="utf-8")
    findings = SourceCodeScanner().scan(str(tmp_path))
    assert findings == []


def test_missing_path_is_safe():
    findings = SourceCodeScanner().scan("/nonexistent/path/xyz")
    assert findings == []


def test_scan_to_dict_shape(tmp_path):
    _write(tmp_path, "bad.py", "eval(x)\n")
    findings = SourceCodeScanner().scan(str(tmp_path))
    d = scan_to_dict(findings, str(tmp_path))
    assert d["total"] >= 1
    assert "root_cause" in d and "fix" in d and "by_severity" in d
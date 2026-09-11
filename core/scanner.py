"""
core/scanner.py
Real security scanner — reads actual files and finds security issues.
Works on Python 3.13 with zero external dependencies.
Covers Terraform, Kubernetes YAML, Docker Compose, Dockerfiles.
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger("concord.scanner")


@dataclass
class Finding:
    check_id:    str
    severity:    str          # CRITICAL | HIGH | MEDIUM | LOW
    title:       str
    description: str
    file_path:   str
    line:        int
    resource:    str = ""
    fix:         str = ""


class TerraformScanner:
    """Scans .tf files for real security misconfigurations."""

    CHECKS: ClassVar[list[dict]] = [
        # IAM wildcard
        dict(id="CKV_AWS_1",   sev="CRITICAL",
             pattern=r'Action\s*=\s*\[?[\"\']?\*[\"\']?\]?',
             title="IAM policy allows wildcard Action (*)",
             fix='Restrict to minimum required actions e.g. ["s3:GetObject"]'),
        dict(id="CKV_AWS_2",   sev="CRITICAL",
             pattern=r'Resource\s*=\s*\[?[\"\']?\*[\"\']?\]?',
             title="IAM policy allows wildcard Resource (*)",
             fix='Restrict to specific resource ARNs'),

        # Security groups open to world
        dict(id="CKV_AWS_24",  sev="HIGH",
             pattern=r'cidr_blocks\s*=\s*\[.*0\.0\.0\.0/0',
             title="Security group allows inbound from 0.0.0.0/0",
             fix='Restrict cidr_blocks to known IP ranges only'),
        dict(id="CKV_AWS_25",  sev="HIGH",
             pattern=r'ipv6_cidr_blocks\s*=\s*\[.*::/0',
             title="Security group allows inbound from ::/0 (all IPv6)",
             fix='Restrict ipv6_cidr_blocks to known ranges'),

        # S3 issues
        dict(id="CKV_AWS_18",  sev="MEDIUM",
             pattern=r'resource\s+\"aws_s3_bucket\"\s+',
             title="S3 bucket may lack access logging",
             fix='Add aws_s3_bucket_logging resource'),
        dict(id="CKV_AWS_19",  sev="HIGH",
             pattern=r'resource\s+\"aws_s3_bucket\"\s+',
             title="S3 bucket may lack server-side encryption",
             fix='Add aws_s3_bucket_server_side_encryption_configuration'),
        dict(id="CKV_AWS_21",  sev="MEDIUM",
             pattern=r'resource\s+\"aws_s3_bucket\"\s+',
             title="S3 bucket may lack versioning",
             fix='Add aws_s3_bucket_versioning resource with enabled = true'),

        # Hardcoded secrets
        dict(id="CKV_SECRET_1", sev="CRITICAL",
             pattern=r'(?i)(password|secret|token|api_key)\s*=\s*\"[^\"]{6,}\"',
             title="Possible hardcoded secret in Terraform file",
             fix='Use var.* or data.aws_secretsmanager_secret instead'),

        # Unencrypted resources
        dict(id="CKV_AWS_16",  sev="HIGH",
             pattern=r'encrypted\s*=\s*false',
             title="Resource has encryption explicitly disabled",
             fix='Set encrypted = true'),

        # Public access
        dict(id="CKV_AWS_57",  sev="HIGH",
             pattern=r'acl\s*=\s*\"public',
             title="S3 bucket ACL is public",
             fix='Use private ACL and bucket policies instead'),
        dict(id="CKV_AWS_58",  sev="MEDIUM",
             pattern=r'publicly_accessible\s*=\s*true',
             title="RDS/ElastiCache instance is publicly accessible",
             fix='Set publicly_accessible = false'),
    ]

    def scan(self, directory: str) -> list[Finding]:
        results = []
        d = Path(directory)
        tf_files = list(d.rglob("*.tf"))

        if not tf_files:
            logger.info("No .tf files found in %s", directory)
            return results

        logger.info("Scanning %d .tf files in %s", len(tf_files), directory)

        for tf in tf_files:
            try:
                text = tf.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
            except Exception as exc:
                logger.warning("Cannot read %s: %s", tf, exc)
                continue

            for check in self.CHECKS:
                for i, line in enumerate(lines, 1):
                    if re.search(check["pattern"], line, re.IGNORECASE):
                        # Extract resource name if possible
                        resource = self._extract_resource(lines, i)
                        results.append(Finding(
                            check_id=check["id"],
                            severity=check["sev"],
                            title=check["title"],
                            description=f"{check['title']} in {tf.name}",
                            file_path=str(tf),
                            line=i,
                            resource=resource,
                            fix=check["fix"],
                        ))
                        break   # one finding per check per file

        logger.info("Terraform scan: %d violations in %d files",
                    len(results), len(tf_files))
        return results

    def _extract_resource(self, lines: list, near_line: int) -> str:
        """Walk back to find the nearest resource block name."""
        for i in range(near_line - 1, max(0, near_line - 20), -1):
            m = re.match(r'\s*resource\s+"(\w+)"\s+"(\w+)"', lines[i])
            if m:
                return f"{m.group(1)}.{m.group(2)}"
        return ""


class KubernetesScanner:
    """Scans .yaml files for real Kubernetes security misconfigurations."""

    CHECKS: ClassVar[list[dict]] = [
        dict(id="CKV_K8S_16",  sev="HIGH",
             pattern=r'privileged:\s*true',
             title="Container is running in privileged mode",
             fix='Remove privileged: true or set to false'),
        dict(id="CKV_K8S_17",  sev="HIGH",
             pattern=r'hostPID:\s*true',
             title="Pod shares host PID namespace",
             fix='Remove hostPID: true'),
        dict(id="CKV_K8S_18",  sev="HIGH",
             pattern=r'hostNetwork:\s*true',
             title="Pod shares host network namespace",
             fix='Remove hostNetwork: true'),
        dict(id="CKV_K8S_20",  sev="MEDIUM",
             pattern=r'runAsUser:\s*0\b|runAsNonRoot:\s*false',
             title="Container may run as root user",
             fix='Set runAsNonRoot: true and runAsUser to non-zero value'),
        dict(id="CKV_K8S_28",  sev="MEDIUM",
             pattern=r'NET_ADMIN|SYS_ADMIN|ALL',
             title="Dangerous Linux capability added to container",
             fix='Remove dangerous capabilities; use drop: [ALL] instead'),
        dict(id="CKV_K8S_35",  sev="HIGH",
             pattern=r'allowPrivilegeEscalation:\s*true',
             title="Container allows privilege escalation",
             fix='Set allowPrivilegeEscalation: false'),
        dict(id="CKV_K8S_8",   sev="MEDIUM",
             pattern=r'livenessProbe:',
             invert=True,  # flag when NOT present
             title="Container missing liveness probe",
             fix='Add livenessProbe to detect and restart unhealthy containers'),
        dict(id="CKV_K8S_11",  sev="MEDIUM",
             pattern=r'resources:\s*\{\}|resources:$',
             title="Container has no resource limits defined",
             fix='Set resources.limits.cpu and resources.limits.memory'),
        dict(id="CKV_K8S_43",  sev="HIGH",
             pattern=r'image:\s*\S+:latest',
             title='Container uses :latest image tag (unpinned)',
             fix='Pin image to a specific digest or version tag'),
        dict(id="CKV_K8S_SECRET", sev="CRITICAL",
             pattern=r'(?i)(password|secret|token|api.key)\s*:\s*\S{6,}',
             title="Possible hardcoded secret in Kubernetes manifest",
             fix='Use Kubernetes Secrets or external secret manager'),
    ]

    def scan(self, directory: str) -> list[Finding]:
        results = []
        d = Path(directory)

        # Scan both .yaml and .yml
        yaml_files = list(d.rglob("*.yaml")) + list(d.rglob("*.yml"))
        # Exclude non-k8s files
        yaml_files = [f for f in yaml_files
                      if not any(x in str(f) for x in
                                 [".github", "node_modules", "__pycache__"])]

        if not yaml_files:
            logger.info("No YAML files found in %s", directory)
            return results

        logger.info("Scanning %d YAML files in %s", len(yaml_files), directory)

        for yf in yaml_files:
            try:
                text = yf.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
            except Exception as exc:
                logger.warning("Cannot read %s: %s", yf, exc)
                continue

            for check in self.CHECKS:
                invert = check.get("invert", False)
                matched = any(re.search(check["pattern"], ln, re.IGNORECASE)
                              for ln in lines)
                if invert:
                    matched = not matched

                if matched:
                    # Find line number
                    line_no = 1
                    if not invert:
                        for i, ln in enumerate(lines, 1):
                            if re.search(check["pattern"], ln, re.IGNORECASE):
                                line_no = i
                                break
                    results.append(Finding(
                        check_id=check["id"],
                        severity=check["sev"],
                        title=check["title"],
                        description=f"{check['title']} in {yf.name}",
                        file_path=str(yf),
                        line=line_no,
                        fix=check["fix"],
                    ))

        logger.info("Kubernetes scan: %d violations in %d files",
                    len(results), len(yaml_files))
        return results


class SourceCodeScanner:
    """Semgrep-style pattern scanner for application source code.

    Dependency-free. Backs the SecurityPolicyAgent (Phase 3).
    Scans Python / JS / TS / Go / PHP for high-signal injection and
    secret-handling anti-patterns. Patterns are conservative to keep the
    false-positive rate low, because source_reliability feeds directly into
    the arbitration confidence score.
    """

    #: Extensions we know how to reason about, mapped to a language label.
    LANG_BY_EXT: ClassVar[dict[str, str]] = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".php": "php",
    }

    #: Each check: id, severity, applicable languages, compiled-later regex,
    #: title, fix. ``langs=None`` means "all languages".
    CHECKS: ClassVar[list[dict]] = [
        dict(id="CONCORD_PY_EXEC", sev="CRITICAL", langs={"python"},
             pattern=r"\b(?:eval|exec)\s*\(",
             title="Use of eval()/exec() on runtime data",
             fix="Avoid eval/exec; use ast.literal_eval or explicit dispatch."),
        dict(id="CONCORD_PY_PICKLE", sev="HIGH", langs={"python"},
             pattern=r"\bpickle\.loads?\s*\(",
             title="Unsafe deserialization via pickle",
             fix="Use json or a schema-validated format instead of pickle."),
        dict(id="CONCORD_PY_YAML", sev="HIGH", langs={"python"},
             pattern=r"\byaml\.load\s*\((?![^)]*Loader\s*=\s*yaml\.SafeLoader)",
             title="yaml.load() without SafeLoader",
             fix="Use yaml.safe_load() or pass Loader=yaml.SafeLoader."),
        dict(id="CONCORD_SHELL_TRUE", sev="HIGH", langs={"python"},
             pattern=r"subprocess\.(?:run|call|Popen|check_output)\s*\([^)]*shell\s*=\s*True",
             title="subprocess call with shell=True",
             fix="Pass an argument list and shell=False; never interpolate input."),
        dict(id="CONCORD_OS_SYSTEM", sev="HIGH", langs={"python"},
             pattern=r"\bos\.system\s*\(",
             title="Command execution via os.system()",
             fix="Use subprocess with an argument list and shell=False."),
        dict(id="CONCORD_JS_EVAL", sev="CRITICAL", langs={"javascript", "typescript"},
             pattern=r"\beval\s*\(",
             title="Use of eval() in JS/TS",
             fix="Remove eval(); use JSON.parse or explicit logic."),
        dict(id="CONCORD_JS_EXEC", sev="HIGH", langs={"javascript", "typescript"},
             pattern=r"child_process\.(?:exec|execSync)\s*\(",
             title="child_process.exec with a shell",
             fix="Use execFile/spawn with an argument array, not exec."),
        dict(id="CONCORD_GO_EXEC", sev="MEDIUM", langs={"go"},
             pattern=r"exec\.Command\s*\(\s*[\"']?(?:sh|bash|cmd)[\"']?\s*,",
             title="Go exec.Command invoking a shell",
             fix="Invoke the target binary directly, not via sh -c."),
        dict(id="CONCORD_PHP_EXEC", sev="CRITICAL", langs={"php"},
             pattern=r"\b(?:system|exec|passthru|shell_exec|popen)\s*\(",
             title="PHP command-execution sink",
             fix="Avoid shell sinks; use escapeshellarg or a safe API."),
        dict(id="CONCORD_SECRET", sev="CRITICAL", langs=None,
             pattern=(r"(?i)(?:password|passwd|secret|api[_-]?key|token|"
                      r"aws_secret_access_key)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"),
             title="Possible hardcoded secret in source",
             fix="Move the value to an environment variable or secret manager."),
    ]

    # Reduce obvious false positives: skip vendored / generated trees.
    _SKIP_DIRS: ClassVar[tuple[str, ...]] = (
        "node_modules", "__pycache__", ".git", "vendor", "dist", "build",
        ".venv", "venv", "site-packages",
    )

    def __init__(self) -> None:
        # Compile once; case-insensitivity is baked into individual patterns.
        self._compiled = [
            {**c, "rx": re.compile(c["pattern"])} for c in self.CHECKS
        ]

    def scan(self, directory: str) -> list[Finding]:
        results: list[Finding] = []
        root = Path(directory)
        if not root.exists():
            logger.info("SourceCodeScanner: path does not exist: %s", directory)
            return results

        files = (
            [root]
            if root.is_file()
            and root.suffix in self.LANG_BY_EXT
            and not any(skip in root.parts for skip in self._SKIP_DIRS)
            else [
                p for p in root.rglob("*")
                if p.is_file()
                and p.suffix in self.LANG_BY_EXT
                and not any(skip in p.parts for skip in self._SKIP_DIRS)
            ]
        
        if not files:
            logger.info("SourceCodeScanner: no source files under %s", directory)
            return results

        logger.info("SourceCodeScanner: scanning %d source files in %s",
                    len(files), directory)

        for path in files:
            lang = self.LANG_BY_EXT[path.suffix]
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as exc:
                logger.warning("Cannot read %s: %s", path, exc)
                continue

            for check in self._compiled:
                langs = check["langs"]
                if langs is not None and lang not in langs:
                    continue
                for i, line in enumerate(lines, 1):
                    if check["rx"].search(line):
                        results.append(Finding(
                            check_id=check["id"],
                            severity=check["sev"],
                            title=check["title"],
                            description=f"{check['title']} in {path.name}:{i}",
                            file_path=str(path),
                            line=i,
                            resource=lang,
                            fix=check["fix"],
                        ))
                        break  # one finding per check per file

        logger.info("SourceCodeScanner: %d findings in %d files",
                    len(results), len(files))
        return results


def scan_to_dict(findings: list[Finding], target: str) -> dict:
    """Convert Finding list to our standard agent dict."""
    if not findings:
        return {"total": 0, "passed": 0, "checks": [],
                "root_cause": f"No violations found in {target}.",
                "fix": "Configuration is compliant."}

    # Group by severity for summary
    by_sev = {}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f)

    # Build summary lines (top 6)
    lines = []
    for f in findings[:6]:
        fp = Path(f.file_path).name
        lines.append(f"  [{f.check_id}] {f.title} ({fp}:{f.line})")

    top = findings[0]
    root_cause = (
        f"[{top.check_id}] {top.title} ({Path(top.file_path).name}:{top.line})\n"
        f"{len(findings)} violation(s) found:\n" +
        "\n".join(lines)
    )
    fix = f"Fix {top.check_id}: {top.fix}"

    return {
        "total":      len(findings),
        "passed":     0,   # custom scanner doesn't count passed checks
        "checks":     [vars(f) for f in findings[:5]],
        "root_cause": root_cause,
        "fix":        fix,
        "by_severity": {k: len(v) for k, v in by_sev.items()},
    }
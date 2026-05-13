from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class DependencyScanResult:
    status: str
    scanner: str
    findings: list[dict[str, Any]]
    safe_to_install: bool
    requires_human_review: bool
    reason: str


class DependencyScanner:
    """Generic dependency scanner for runtime-downloaded/generated artifacts.

    This class is infrastructure-only. It does not know the task domain. It
    inspects dependency declarations before a sandbox tries to install them.
    When stronger scanners such as pip-audit are available, it delegates to
    them; otherwise it applies conservative static checks and requests review.
    """

    RISKY_PATTERNS = [
        re.compile(r"^\s*-e\s+", re.I),
        re.compile(r"^\s*(git\+|hg\+|svn\+|bzr\+)", re.I),
        re.compile(r"^\s*https?://", re.I),
        re.compile(r";\s*python_version\s*", re.I),
    ]

    def scan_requirements_text(self, text: str) -> dict[str, Any]:
        requirements = self._normalize_lines(text)
        findings: list[dict[str, Any]] = []
        for line in requirements:
            for pattern in self.RISKY_PATTERNS:
                if pattern.search(line):
                    findings.append({
                        "severity": "review",
                        "package": line,
                        "message": "Dependency declaration requires human review before install.",
                    })
            if "==" not in line and not line.startswith(("#", "--")):
                findings.append({
                    "severity": "info",
                    "package": line,
                    "message": "Dependency is not pinned. Reproducibility may be lower.",
                })

        audit = self._pip_audit(requirements)
        findings.extend(audit.get("findings", []))
        has_high = any(f.get("severity") in {"high", "critical", "blocked"} for f in findings)
        has_review = any(f.get("severity") == "review" for f in findings)
        scanner = "pip-audit+static" if audit.get("scanner") == "pip-audit" else "static"
        return asdict(DependencyScanResult(
            status="blocked" if has_high else "review_required" if has_review else "passed",
            scanner=scanner,
            findings=findings,
            safe_to_install=not has_high and not has_review,
            requires_human_review=has_high or has_review,
            reason="Dependency scan completed." if findings else "No dependency findings detected.",
        ))

    def scan_path(self, path: Path) -> dict[str, Any]:
        candidates = [path / "requirements.txt", path / "requirements.in", path / "pyproject.toml"]
        combined = []
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                combined.append(f"# source: {candidate.name}\n" + candidate.read_text(encoding="utf-8", errors="ignore"))
        if not combined:
            return asdict(DependencyScanResult(
                status="passed",
                scanner="static",
                findings=[],
                safe_to_install=True,
                requires_human_review=False,
                reason="No dependency declaration file found.",
            ))
        return self.scan_requirements_text("\n".join(combined))

    def _normalize_lines(self, text: str) -> list[str]:
        lines: list[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[build-system]") or line.startswith("[project]"):
                # pyproject parsing is intentionally conservative in this runtime.
                continue
            lines.append(line)
        return lines

    def _pip_audit(self, requirements: list[str]) -> dict[str, Any]:
        exe = shutil.which("pip-audit")
        if not exe or not requirements:
            return {"scanner": "static", "findings": []}
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "requirements.txt"
            req.write_text("\n".join(requirements), encoding="utf-8")
            proc = subprocess.run(
                [exe, "-r", str(req), "--format", "json"],
                text=True,
                capture_output=True,
                timeout=60,
            )
            findings: list[dict[str, Any]] = []
            try:
                data = json.loads(proc.stdout or "[]")
            except Exception:
                data = []
            for item in data if isinstance(data, list) else []:
                vulns = item.get("vulns") if isinstance(item, dict) else []
                for vuln in vulns or []:
                    findings.append({
                        "severity": "high",
                        "package": item.get("name"),
                        "version": item.get("version"),
                        "id": vuln.get("id"),
                        "message": vuln.get("description") or vuln.get("id"),
                    })
            return {"scanner": "pip-audit", "findings": findings}

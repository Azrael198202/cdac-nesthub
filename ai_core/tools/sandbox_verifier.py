from __future__ import annotations

import ast
import json
import py_compile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class SandboxVerificationResult:
    status: str
    checks: list[dict[str, Any]]
    safe_to_register: bool
    requires_human_review: bool
    reason: str


class SandboxVerifier:
    """Static and compile-time verifier for runtime-generated artifacts.

    This is not a full security sandbox. It is a generic preflight gate that
    prevents obviously unsafe artifacts from being registered without review.
    Runtime execution should still happen in an OS/container sandbox when the
    artifact uses network, filesystem, subprocess, or package installation.
    """

    BLOCKED_IMPORTS = {
        "subprocess",
        "os",
        "pty",
        "socketserver",
        "ftplib",
        "telnetlib",
        "shutil",
    }
    BLOCKED_CALLS = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
    }

    def verify_tool_artifact(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        files = artifact.get("files") if isinstance(artifact.get("files"), dict) else {}
        code = files.get("tool.py") or files.get("module.py") or ""
        return asdict(self.verify_python_source(source=str(code), artifact=artifact))

    def verify_python_source(self, *, source: str, artifact: dict[str, Any] | None = None) -> SandboxVerificationResult:
        checks: list[dict[str, Any]] = []
        if not source.strip():
            return SandboxVerificationResult(
                status="failed",
                checks=[{"name": "source_present", "status": "failed", "message": "no python source provided"}],
                safe_to_register=False,
                requires_human_review=True,
                reason="No executable source was provided.",
            )

        syntax_ok = self._check_syntax(source)
        checks.append(syntax_ok)
        if syntax_ok["status"] != "passed":
            return SandboxVerificationResult("failed", checks, False, True, "Python syntax validation failed.")

        static_check = self._check_static_policy(source)
        checks.append(static_check)
        if static_check["status"] != "passed":
            return SandboxVerificationResult("blocked", checks, False, True, "Static safety policy blocked the artifact.")

        compile_check = self._check_compile(source)
        checks.append(compile_check)
        if compile_check["status"] != "passed":
            return SandboxVerificationResult("failed", checks, False, True, "Compile validation failed.")

        manifest = (artifact or {}).get("manifest") if isinstance((artifact or {}).get("manifest"), dict) else {}
        safety = manifest.get("safety") if isinstance(manifest.get("safety"), dict) else {}
        requires_review = bool((artifact or {}).get("requires_review") or safety.get("requires_human_confirmation"))
        return SandboxVerificationResult(
            status="passed",
            checks=checks,
            safe_to_register=not requires_review,
            requires_human_review=requires_review,
            reason="Artifact passed generic static and compile checks.",
        )

    def _check_syntax(self, source: str) -> dict[str, Any]:
        try:
            ast.parse(source)
            return {"name": "python_syntax", "status": "passed"}
        except SyntaxError as exc:
            return {"name": "python_syntax", "status": "failed", "message": str(exc)}

    def _check_static_policy(self, source: str) -> dict[str, Any]:
        tree = ast.parse(source)
        findings: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = str(alias.name).split(".")[0]
                    if root in self.BLOCKED_IMPORTS:
                        findings.append(f"blocked import: {root}")
            if isinstance(node, ast.ImportFrom):
                root = str(node.module or "").split(".")[0]
                if root in self.BLOCKED_IMPORTS:
                    findings.append(f"blocked import: {root}")
            if isinstance(node, ast.Call):
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in self.BLOCKED_CALLS:
                    findings.append(f"blocked call: {name}")
        if findings:
            return {"name": "static_policy", "status": "blocked", "findings": findings}
        return {"name": "static_policy", "status": "passed"}

    def _check_compile(self, source: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.py"
            path.write_text(source, encoding="utf-8")
            try:
                py_compile.compile(str(path), doraise=True)
                return {"name": "py_compile", "status": "passed"}
            except py_compile.PyCompileError as exc:
                return {"name": "py_compile", "status": "failed", "message": str(exc)}

    def write_report(self, *, report_path: Path, result: dict[str, Any]) -> None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

from __future__ import annotations

import ast
import json
import py_compile
import tempfile
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from auxiliary_brain.runtime_codegen.dynamic_value_hardcode_detector import DynamicValueHardcodeDetector


@dataclass
class SandboxVerificationResult:
    status: str
    checks: list[dict[str, Any]]
    safe_to_register: bool
    requires_human_review: bool
    reason: str


class SandboxVerifier:
    """Static and compile-time verifier for runtime-generated artifacts.

    This is not a full security sandbox. It is a generic precheck gate that
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

        static_check = self._check_static_policy(source, artifact=artifact)
        checks.append(static_check)
        if static_check["status"] != "passed":
            return SandboxVerificationResult("blocked", checks, False, True, "Static safety policy blocked the artifact.")

        entrypoint_check = self._check_entrypoint(source, artifact=artifact)
        checks.append(entrypoint_check)
        if entrypoint_check["status"] != "passed":
            return SandboxVerificationResult("failed", checks, False, True, entrypoint_check.get("message", "Runtime entrypoint validation failed."))

        dynamic_value_check = self._check_dynamic_value_hardcoding(source, artifact=artifact)
        checks.append(dynamic_value_check)
        if dynamic_value_check["status"] != "passed":
            return SandboxVerificationResult("failed", checks, False, True, "Generated artifact hardcoded runtime values and is not reusable.")

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

    def _check_static_policy(self, source: str, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
        tree = ast.parse(source)
        findings: list[str] = []
        declared = self._declared_python_packages(artifact or {})
        stdlib = set(getattr(sys, "stdlib_module_names", set()))
        allowed_third_party = declared | {"requests"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = str(alias.name).split(".")[0]
                    if root in self.BLOCKED_IMPORTS:
                        findings.append(f"blocked import: {root}")
                    elif root not in stdlib and root not in allowed_third_party:
                        findings.append(f"undeclared third-party import: {root}")
            if isinstance(node, ast.ImportFrom):
                root = str(node.module or "").split(".")[0]
                if root in self.BLOCKED_IMPORTS:
                    findings.append(f"blocked import: {root}")
                elif root and root not in stdlib and root not in allowed_third_party:
                    findings.append(f"undeclared third-party import: {root}")
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

    def _declared_python_packages(self, artifact: dict[str, Any]) -> set[str]:
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        deps = manifest.get("dependencies") if isinstance(manifest.get("dependencies"), dict) else {}
        packages = deps.get("python_packages") if isinstance(deps.get("python_packages"), list) else []
        out = set()
        for item in packages:
            name = str(item).split("==")[0].split(">=")[0].split("[")[0].strip().replace("-", "_")
            if name:
                out.add(name)
        return out

    def _expected_entrypoint(self, artifact: dict[str, Any] | None) -> str:
        manifest = (artifact or {}).get("manifest") if isinstance((artifact or {}).get("manifest"), dict) else {}
        implementation = manifest.get("implementation") if isinstance(manifest.get("implementation"), dict) else {}
        return str(implementation.get("function") or implementation.get("callable") or "run")

    def _check_entrypoint(self, source: str, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
        expected = self._expected_entrypoint(artifact)
        tree = ast.parse(source)
        functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if expected not in functions:
            return {
                "name": "runtime_entrypoint",
                "status": "failed",
                "expected_function": expected,
                "available_functions": sorted(functions),
                "message": f"Generated artifact must define callable entrypoint {expected}(payload: dict) -> dict.",
            }
        fn = functions[expected]
        positional_args = list(fn.args.posonlyargs) + list(fn.args.args)
        if len(positional_args) != 1:
            return {
                "name": "runtime_entrypoint",
                "status": "failed",
                "expected_function": expected,
                "message": f"Generated artifact entrypoint {expected} must accept exactly one payload argument.",
            }
        if positional_args[0].arg != "payload":
            return {
                "name": "runtime_entrypoint",
                "status": "failed",
                "expected_function": expected,
                "message": f"Generated artifact entrypoint {expected} must name its argument payload.",
            }
        return {"name": "runtime_entrypoint", "status": "passed", "expected_function": expected}


    def _runtime_variables(self, artifact: dict[str, Any] | None) -> list[dict[str, Any]]:
        artifact = artifact or {}
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        for value in (artifact.get("runtime_variables"), manifest.get("runtime_variables")):
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return []

    def _check_dynamic_value_hardcoding(self, source: str, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
        variables = self._runtime_variables(artifact)
        result = DynamicValueHardcodeDetector().detect(source, variables)
        if result.get("passed"):
            return {"name": "dynamic_runtime_value_hardcoding", "status": "passed", "checked_runtime_variables": result.get("checked_runtime_variables", [])}
        return {"name": "dynamic_runtime_value_hardcoding", "status": "failed", "findings": result.get("findings", []), "checked_runtime_variables": result.get("checked_runtime_variables", [])}

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

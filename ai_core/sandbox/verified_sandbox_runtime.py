from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ai_core.security.dependency_scanner import DependencyScanner
from ai_core.tools.sandbox_verifier import SandboxVerifier


@dataclass
class VerifiedSandboxResult:
    status: str
    mode: str
    checks: list[dict[str, Any]]
    safe_to_register: bool
    requires_human_review: bool
    reason: str
    stdout: str = ""
    stderr: str = ""


class VerifiedSandboxRuntime:
    """Verify runtime artifacts in an isolated Docker or venv sandbox.

    The sandbox is generic. It does not know the capability domain. It writes the
    generated artifact to a temporary workspace, scans dependencies, compiles the
    code, imports the declared callable, and runs it with the supplied test input.
    Docker is preferred when available; a temporary venv fallback is used when
    Docker is unavailable.
    """

    def __init__(self) -> None:
        self.static_verifier = SandboxVerifier()
        self.dependency_scanner = DependencyScanner()

    def verify_tool_artifact(
        self,
        *,
        artifact: dict[str, Any],
        test_input: dict[str, Any] | None = None,
        allow_network: bool = False,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        static_result = self.static_verifier.verify_tool_artifact(artifact=artifact)
        checks.append({"name": "static_artifact_verification", "result": static_result})
        if not static_result.get("safe_to_register") and static_result.get("status") != "passed":
            return asdict(VerifiedSandboxResult(
                status="blocked",
                mode="static",
                checks=checks,
                safe_to_register=False,
                requires_human_review=True,
                reason="Static verification failed before sandbox execution.",
            ))

        with tempfile.TemporaryDirectory(prefix="verified_runtime_") as tmp:
            root = Path(tmp)
            self._write_artifact(root, artifact)
            dep_scan = self.dependency_scanner.scan_path(root)
            checks.append({"name": "dependency_scan", "result": dep_scan})
            if not dep_scan.get("safe_to_install"):
                return asdict(VerifiedSandboxResult(
                    status="review_required",
                    mode="dependency_scan",
                    checks=checks,
                    safe_to_register=False,
                    requires_human_review=True,
                    reason="Dependency scan requires review before sandbox execution.",
                ))

            callable_info = self._callable_info(root, artifact)
            runner = self._write_runner(root, callable_info, test_input or {})
            if shutil.which("docker"):
                result = self._run_in_docker(root, runner, allow_network=allow_network, timeout_seconds=timeout_seconds)
                if result.get("returncode") != 0:
                    fallback = self._run_in_venv(root, runner, timeout_seconds=timeout_seconds)
                    fallback.setdefault("checks", []).insert(0, {
                        "name": "docker_sandbox_fallback",
                        "message": "Docker sandbox failed or image unavailable; temporary venv fallback was used.",
                        "docker_stderr": result.get("stderr", "")[-1000:],
                    })
                    result = fallback
            else:
                result = self._run_in_venv(root, runner, timeout_seconds=timeout_seconds)
            checks.extend(result.get("checks", []))
            passed = result.get("returncode") == 0
            return asdict(VerifiedSandboxResult(
                status="passed" if passed else "failed",
                mode=result.get("mode", "unknown"),
                checks=checks,
                safe_to_register=passed,
                requires_human_review=not passed,
                reason="Sandbox execution test passed." if passed else "Sandbox execution test failed.",
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
            ))

    def _write_artifact(self, root: Path, artifact: dict[str, Any]) -> None:
        files = artifact.get("files") if isinstance(artifact.get("files"), dict) else {}
        if not files:
            raise ValueError("Artifact has no files to verify.")
        for name, content in files.items():
            path = self._safe_child_path(root, str(name))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        (root / "artifact_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _safe_child_path(self, base: Path, relative_name: str) -> Path:
        pure = PurePosixPath(relative_name.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"Unsafe artifact path: {relative_name}")
        return base / Path(*pure.parts)

    def _callable_info(self, root: Path, artifact: dict[str, Any]) -> dict[str, str]:
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        implementation = manifest.get("implementation") if isinstance(manifest.get("implementation"), dict) else {}
        module_path = implementation.get("module_path") or implementation.get("path") or "tool.py"
        function = implementation.get("function") or implementation.get("callable") or "run"
        module_path = Path(str(module_path)).name
        if not (root / module_path).exists():
            files = artifact.get("files") if isinstance(artifact.get("files"), dict) else {}
            module_path = Path(next(iter(files.keys()))).name
        return {"module_path": module_path, "function": str(function)}

    def _write_runner(self, root: Path, callable_info: dict[str, str], test_input: dict[str, Any]) -> Path:
        payload_path = root / "sandbox_input.json"
        payload_path.write_text(json.dumps(test_input, ensure_ascii=False), encoding="utf-8")
        runner = root / "sandbox_runner.py"
        runner.write_text(
            "import importlib.util, json, pathlib, sys\n"
            "root = pathlib.Path(__file__).parent\n"
            f"module_path = root / {callable_info['module_path']!r}\n"
            f"func_name = {callable_info['function']!r}\n"
            "spec = importlib.util.spec_from_file_location('runtime_artifact', module_path)\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "assert spec and spec.loader\n"
            "spec.loader.exec_module(mod)\n"
            "fn = getattr(mod, func_name)\n"
            "payload = json.loads((root / 'sandbox_input.json').read_text(encoding='utf-8'))\n"
            "result = fn(payload)\n"
            "print(json.dumps({'sandbox_result_type': type(result).__name__, 'result': result}, ensure_ascii=False, default=str))\n",
            encoding="utf-8",
        )
        return runner

    def _run_in_docker(self, root: Path, runner: Path, *, allow_network: bool, timeout_seconds: int) -> dict[str, Any]:
        network = "bridge" if allow_network else "none"
        cmd = [
            "docker", "run", "--rm", "--network", network,
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "-v", f"{root}:/work:ro", "-w", "/work", "python:3.12-slim",
            "python", str(PurePosixPath("/work") / runner.name),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
        return {"mode": "docker", "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "checks": [{"name": "docker_sandbox_execution", "returncode": proc.returncode}]}

    def _run_in_venv(self, root: Path, runner: Path, *, timeout_seconds: int) -> dict[str, Any]:
        venv = root / ".venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True, text=True, timeout=timeout_seconds)
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        proc = subprocess.run([str(py), str(runner)], cwd=str(root), capture_output=True, text=True, timeout=timeout_seconds)
        return {"mode": "venv", "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "checks": [{"name": "venv_sandbox_execution", "returncode": proc.returncode}]}

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ai_core.utils.safe_subprocess import run_text
from ai_core.security.dependency_scanner import DependencyScanner
from ai_core.tools.sandbox_verifier import SandboxVerifier
from ai_core.utils.safe_json import make_json_safe, safe_json_dumps


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

    def _project_root(self) -> Path:
        """Return the source root that contains ai_core.

        Generated artifacts may import generic runtime support modules. The
        sandbox keeps the generated artifact isolated while exposing this root
        read-only/through PYTHONPATH so those generic support modules can be
        imported during verification.
        """
        return Path(__file__).resolve().parents[2]

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
                reason=self._summarize_static_failure(static_result),
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
            sandbox_error = self._sandbox_stdout_error(result.get("stdout", ""))
            if sandbox_error:
                checks.append({"name": "sandbox_result_error_classifier", "result": sandbox_error})
            passed = result.get("returncode") == 0 and not sandbox_error
            return asdict(VerifiedSandboxResult(
                status="passed" if passed else "failed",
                mode=result.get("mode", "unknown"),
                checks=checks,
                safe_to_register=passed,
                requires_human_review=not passed,
                reason="Sandbox execution test passed." if passed else (sandbox_error.get("message") if sandbox_error else "Sandbox execution test failed."),
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
            ))

    def _sandbox_stdout_error(self, stdout: str) -> dict[str, Any] | None:
        """Treat structured error output as sandbox failure even with exit code 0."""
        text = str(stdout or "").strip()
        if not text:
            return None
        last_line = text.splitlines()[-1].strip()
        try:
            payload = json.loads(last_line)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("status") in {"failed", "error", "failure"}:
            return {"status": "failed", "message": "Sandbox runner reported failure.", "payload": make_json_safe(payload)}
        result = payload.get("result")
        if isinstance(result, dict) and result.get("error"):
            return {"status": "failed", "message": "Sandbox result contains error output.", "payload": make_json_safe(result)}
        return None

    def _summarize_static_failure(self, static_result: dict[str, Any]) -> str:
        checks = static_result.get("checks") if isinstance(static_result.get("checks"), list) else []
        findings: list[str] = []
        for check in checks:
            if not isinstance(check, dict):
                continue
            if check.get("message"):
                findings.append(str(check.get("message")))
            for item in check.get("findings", []) if isinstance(check.get("findings"), list) else []:
                findings.append(str(item))
        if findings:
            return "Static verification failed before sandbox execution: " + "; ".join(findings[:8])
        return str(static_result.get("reason") or "Static verification failed before sandbox execution.")


    def verify_module_artifact(
        self,
        *,
        artifact: dict[str, Any],
        test_input: dict[str, Any] | None = None,
        allow_network: bool = False,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        """Verify a runtime module artifact with the same generic sandbox path.

        Module artifacts use module.py/run by convention. The implementation is
        domain-neutral and delegates to the shared artifact sandbox runner.
        """
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        implementation = manifest.get("implementation") if isinstance(manifest.get("implementation"), dict) else {}
        implementation.setdefault("module_path", "module.py")
        implementation.setdefault("function", "run")
        manifest["implementation"] = implementation
        artifact["manifest"] = manifest
        return self.verify_tool_artifact(
            artifact=artifact,
            test_input=test_input,
            allow_network=allow_network,
            timeout_seconds=timeout_seconds,
        )

    def _write_artifact(self, root: Path, artifact: dict[str, Any]) -> None:
        files = artifact.get("files") if isinstance(artifact.get("files"), dict) else {}
        if not files:
            raise ValueError("Artifact has no files to verify.")
        for name, content in files.items():
            path = self._safe_child_path(root, str(name))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        (root / "artifact_manifest.json").write_text(safe_json_dumps(manifest, indent=2), encoding="utf-8")

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
        payload_path.write_text(safe_json_dumps(test_input), encoding="utf-8")
        runner = root / "sandbox_runner.py"
        runner.write_text(
            "import dataclasses, importlib.util, json, pathlib, sys\n"
            "root = pathlib.Path(__file__).parent\n"
            f"module_path = root / {callable_info['module_path']!r}\n"
            f"func_name = {callable_info['function']!r}\n"
            "def _safe(obj, seen=None):\n"
            "    if seen is None: seen=set()\n"
            "    if obj is None or isinstance(obj, (str, int, float, bool)): return obj\n"
            "    oid=id(obj)\n"
            "    if isinstance(obj, (dict, list, tuple, set)) or dataclasses.is_dataclass(obj):\n"
            "        if oid in seen: return {'__circular_reference__': True, 'type': type(obj).__name__}\n"
            "        seen.add(oid)\n"
            "        try:\n"
            "            if dataclasses.is_dataclass(obj): return _safe(dataclasses.asdict(obj), seen)\n"
            "            if isinstance(obj, dict): return {str(k): _safe(v, seen) for k, v in obj.items()}\n"
            "            return [_safe(x, seen) for x in list(obj)]\n"
            "        finally:\n"
            "            seen.discard(oid)\n"
            "    if isinstance(obj, pathlib.Path): return str(obj)\n"
            "    if isinstance(obj, BaseException): return {'error_type': type(obj).__name__, 'message': str(obj)}\n"
            "    if callable(obj): return {'__callable__': getattr(obj, '__name__', type(obj).__name__)}\n"
            "    try:\n"
            "        json.dumps(obj); return obj\n"
            "    except Exception:\n"
            "        return repr(obj)\n"
            "def _emit(payload, code=0):\n"
            "    print(json.dumps(_safe(payload), ensure_ascii=False))\n"
            "    sys.exit(code)\n"
            "if not module_path.exists():\n"
            "    _emit({'status':'failed','error_type':'missing_module_file','message':f'Module file not found: {module_path.name}'}, 1)\n"
            "spec = importlib.util.spec_from_file_location('runtime_artifact', module_path)\n"
            "if spec is None or spec.loader is None:\n"
            "    _emit({'status':'failed','error_type':'module_load_failed','message':'Could not create module spec.'}, 1)\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "try:\n"
            "    spec.loader.exec_module(mod)\n"
            "except Exception as exc:\n"
            "    _emit({'status':'failed','error_type':'module_import_failed','error':exc}, 1)\n"
            "fn = getattr(mod, func_name, None)\n"
            "if fn is None:\n"
            "    available=[name for name in dir(mod) if callable(getattr(mod, name, None)) and not name.startswith('_')]\n"
            "    _emit({'status':'failed','error_type':'missing_entrypoint','message':f'Generated artifact must define {func_name}(payload: dict) -> dict.','available_callables':available}, 1)\n"
            "if not callable(fn):\n"
            "    _emit({'status':'failed','error_type':'entrypoint_not_callable','message':f'{func_name} exists but is not callable.'}, 1)\n"
            "payload = json.loads((root / 'sandbox_input.json').read_text(encoding='utf-8'))\n"
            "try:\n"
            "    result = fn(payload)\n"
            "except Exception as exc:\n"
            "    _emit({'status':'failed','error_type':'entrypoint_execution_failed','error':exc}, 1)\n"
            "if not isinstance(result, dict):\n"
            "    _emit({'status':'failed','error_type':'invalid_result_type','message':'run(payload) must return a dict.','actual_type':type(result).__name__,'result':result}, 1)\n"
            "_emit({'status':'passed','sandbox_result_type': type(result).__name__, 'result': result}, 0)\n",
            encoding="utf-8",
        )
        return runner

    def _run_in_docker(self, root: Path, runner: Path, *, allow_network: bool, timeout_seconds: int) -> dict[str, Any]:
        network = "bridge" if allow_network else "none"
        project_root = self._project_root()
        cmd = [
            "docker", "run", "--rm", "--network", network,
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "-v", f"{root}:/work:ro",
            "-v", f"{project_root}:/project:ro",
            "-e", "PYTHONPATH=/project",
            "-w", "/work", "python:3.12-slim",
            "python", str(PurePosixPath("/work") / runner.name),
        ]
        proc = run_text(cmd, capture_output=True, text=True, timeout=timeout_seconds)
        return {"mode": "docker", "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "checks": [{"name": "docker_sandbox_execution", "returncode": proc.returncode}]}

    def _run_in_venv(self, root: Path, runner: Path, *, timeout_seconds: int) -> dict[str, Any]:
        venv = root / ".venv"
        run_text([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True, text=True, timeout=timeout_seconds)
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = os.environ.copy()
        project_root = str(self._project_root())
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = project_root if not existing else project_root + os.pathsep + existing
        checks = []
        proc = run_text([str(py), str(runner)], cwd=str(root), env=env, capture_output=True, text=True, timeout=timeout_seconds)
        checks.append({"name": "venv_sandbox_execution", "returncode": proc.returncode})

        # Generic one-shot dependency recovery for generated artifacts.  This is
        # not a substitute for the zero-dependency generation policy; it only
        # prevents a missing optional package from crashing the verification path
        # without a clear repair attempt.
        if proc.returncode != 0:
            missing = self._missing_python_module(proc.stdout + "\n" + proc.stderr)
            if missing:
                install = run_text([str(py), "-m", "pip", "install", missing], cwd=str(root), env=env, capture_output=True, text=True, timeout=max(120, timeout_seconds))
                checks.append({"name": "venv_missing_python_dependency_repair", "package": missing, "returncode": install.returncode, "stderr_tail": (install.stderr or "")[-500:]})
                if install.returncode == 0:
                    proc = run_text([str(py), str(runner)], cwd=str(root), env=env, capture_output=True, text=True, timeout=timeout_seconds)
                    checks.append({"name": "venv_sandbox_execution_after_dependency_repair", "returncode": proc.returncode})

        return {"mode": "venv", "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "checks": checks}

    def _missing_python_module(self, text: str) -> str:
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", str(text or ""))
        if not match:
            return ""
        name = match.group(1).split(".")[0].strip()
        # Keep package recovery generic and conservative.
        if not name or not re.match(r"^[A-Za-z0-9_.-]{1,80}$", name):
            return ""
        return name

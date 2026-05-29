from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import sysconfig
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from contextlib import nullcontext

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED, RUNTIME_REGISTRY


@dataclass(frozen=True)
class TemplateMatch:
    template: dict[str, Any]
    score: int


class RuntimeCapabilityGapImplementer:
    """Generic runtime capability implementation lifecycle.

    ai_core stays generic: it does not contain concrete capability code.
    It loads runtime capability templates from configuration, resolves declared
    dependencies, writes artifacts under runtime/generated, validates them in a
    sandbox-like subprocess, verifies the registered callable, and registers only
    after validation succeeds.
    """

    def __init__(self, *, template_path: Path | None = None) -> None:
        self.template_path = template_path or (CONFIGS_DIR / "runtime_capability_templates.json")
        self.generated_dir = RUNTIME_GENERATED / "tools"
        self.generated_tests_dir = RUNTIME_GENERATED / "tests"
        self.registry_path = RUNTIME_REGISTRY / "tool_registry.json"
        self.module_registry_path = RUNTIME_REGISTRY / "module_registry.json"

    def implement_if_requested(
        self,
        *,
        user_input: str,
        evidence: dict[str, Any],
        run_id: str,
        allow_implementation: bool,
    ) -> dict[str, Any]:
        if not allow_implementation:
            return {"status": "not_requested", "reason": "implementation_was_not_requested"}
        urls = evidence.get("urls") if isinstance(evidence.get("urls"), list) else []
        templates = self._load_templates()
        match = self._select_template(str(user_input or ""), templates)
        if not match:
            return {
                "status": "blocked",
                "reason": "no_runtime_template_matched_requested_capability",
                "template_path": str(self.template_path),
            }
        template = match.template
        acquisition_policy = template.get("acquisition_policy") if isinstance(template.get("acquisition_policy"), dict) else {}
        allow_policy_backed_basic = bool(acquisition_policy.get("allow_policy_backed_basic_acquisition_without_external_evidence"))
        if not urls and not allow_policy_backed_basic:
            return {"status": "blocked", "reason": "verified_evidence_required_before_implementation"}
        if not urls and allow_policy_backed_basic:
            evidence = dict(evidence)
            evidence["urls"] = ["runtime-policy://basic-generated-capability-contract"]
            evidence["source_note"] = "External source retrieval was unavailable; a basic runtime-generated template with sandbox validation is allowed by capability acquisition policy."
        dependency_resolution = self._resolve_dependencies(template)
        if not dependency_resolution.get("passed"):
            return {
                "status": "dependency_resolution_failed",
                "template_id": template.get("template_id"),
                "score": match.score,
                "dependency_resolution": dependency_resolution,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        artifact = self._write_artifact(template=template, run_id=run_id, evidence=evidence, dependency_resolution=dependency_resolution)
        validation = self._validate_artifact(artifact)
        cleanliness = self._validate_generated_artifact_cleanliness(template=template, artifact=artifact)
        if not cleanliness.get("passed"):
            validation = {
                "passed": False,
                "status": "failed",
                "reason": "generated_artifact_cleanliness_failed",
                "checks": (validation.get("checks") if isinstance(validation, dict) else []) + [cleanliness],
            }
        verification_run: dict[str, Any] | None = None
        registration: dict[str, Any] | None = None
        if validation.get("passed"):
            verification_run = self._execute_verification_run(template=template, artifact=artifact)
            if verification_run.get("passed"):
                registration = self._register_artifact(
                    template=template,
                    artifact=artifact,
                    validation=validation,
                    verification_run=verification_run,
                    dependency_resolution=dependency_resolution,
                    evidence=evidence,
                )
                status = "implemented_tested_registered"
            else:
                status = "generated_but_verification_failed"
        else:
            status = "generated_but_validation_failed"
        return {
            "status": status,
            "template_id": template.get("template_id"),
            "score": match.score,
            "dependency_resolution": dependency_resolution,
            "artifact": artifact if 'artifact' in locals() else None,
            "validation": validation if 'validation' in locals() else None,
            "verification_run": verification_run,
            "registration": registration,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _load_templates(self) -> list[dict[str, Any]]:
        if not self.template_path.exists():
            return []
        try:
            data = json.loads(self.template_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return []
        templates = data.get("templates") if isinstance(data, dict) else data
        return [x for x in templates if isinstance(x, dict)] if isinstance(templates, list) else []

    def _select_template(self, user_input: str, templates: list[dict[str, Any]]) -> TemplateMatch | None:
        value = " " + user_input.casefold() + " "
        best: TemplateMatch | None = None
        for template in templates:
            terms = template.get("match_terms") if isinstance(template.get("match_terms"), list) else []
            required = template.get("required_terms") if isinstance(template.get("required_terms"), list) else []
            if required and not all(str(term).casefold() in value for term in required):
                continue
            score = sum(1 for term in terms if str(term).casefold() in value)
            if score <= 0:
                continue
            candidate = TemplateMatch(template=template, score=score)
            if best is None or candidate.score > best.score:
                best = candidate
        return best

    def _resolve_dependencies(self, template: dict[str, Any]) -> dict[str, Any]:
        dependencies = template.get("dependencies") if isinstance(template.get("dependencies"), list) else []
        checks: list[dict[str, Any]] = []
        if not dependencies:
            return {"passed": True, "status": "not_required", "checks": checks}
        for item in dependencies:
            if not isinstance(item, dict):
                continue
            import_name = str(item.get("import_name") or item.get("module") or "").strip()
            package_name = str(item.get("package") or item.get("name") or import_name).strip()
            auto_install = bool(item.get("auto_install", True))
            check = {"package": package_name, "import_name": import_name, "auto_install": auto_install}
            if import_name and self._module_available(import_name):
                check.update({"status": "available", "installed": False})
                checks.append(check)
                continue
            if not package_name or not auto_install:
                check.update({"status": "missing", "installed": False})
                checks.append(check)
                return {"passed": False, "status": "missing_dependency", "checks": checks}
            pip_proc = self._pip_install(package_name)
            check.update({
                "status": "installed" if pip_proc.get("returncode") == 0 else "install_failed",
                "installed": pip_proc.get("returncode") == 0,
                "pip": pip_proc,
            })
            if pip_proc.get("returncode") != 0:
                checks.append(check)
                return {"passed": False, "status": "dependency_installation_failed", "checks": checks}
            if import_name and not self._module_available(import_name):
                check["status"] = "install_completed_but_import_failed"
                checks.append(check)
                return {"passed": False, "status": "dependency_import_verification_failed", "checks": checks}
            checks.append(check)
        return {"passed": True, "status": "completed", "checks": checks}

    def _module_available(self, name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except Exception:
            return False

    def _validation_python_executable(self) -> str:
        """Pick a real Python interpreter for generated-artifact validation.

        IDE launchers can make ``sys.executable`` behave like a debugger
        bootstrap process.  Candidate interpreters are self-tested with the same
        minimal environment used for validation; any candidate that starts
        debugpy/pydevd is rejected before generated code is validated.
        """
        candidates: list[str] = []
        for candidate in (
            str(getattr(sys, "_base_executable", "") or ""),
            str(sys.executable or ""),
            str(Path(str(sysconfig.get_config_var("BINDIR") or "")) / ("python.exe" if os.name == "nt" else "python")) if sysconfig.get_config_var("BINDIR") else "",
            str(shutil.which("python") or ""),
            str(shutil.which("python3") or ""),
        ):
            value = candidate.strip()
            if value and value not in candidates:
                candidates.append(value)
        for candidate in candidates:
            lowered = candidate.casefold()
            if "debugpy" in lowered or "pydevd" in lowered or "vscode" in lowered or "pycharm" in lowered:
                continue
            if self._python_candidate_is_clean(candidate):
                return candidate
        return sys.executable

    def _python_candidate_is_clean(self, candidate: str) -> bool:
        try:
            with self._skip_debugger_subprocess_patch():
                proc = subprocess.run(
                    [candidate, "-I", "-c", "import sys; print(sys.executable)"],
                    env=self._clean_subprocess_env(minimal=True),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                )
        except Exception:
            return False
        combined = (str(proc.stdout or "") + "\n" + str(proc.stderr or "")).casefold()
        if proc.returncode != 0:
            return False
        return not any(token in combined for token in ("debugpy", "pydevd", ".vscode", "vscode", "pycharm"))

    def _skip_debugger_subprocess_patch(self):
        """Disable debugger subprocess argument injection around validation launches.

        VS Code/debugpy can monkey-patch subprocess.Popen when its launch
        configuration has subprocess debugging enabled.  Cleaning environment
        variables alone is not enough in that case because the parent process can
        rewrite child command arguments before process creation.  pydevd exposes
        a context manager for this exact situation; when it is unavailable this
        method becomes a harmless no-op.
        """
        try:
            import pydevd  # type: ignore
            cm = getattr(pydevd, "skip_subprocess_arg_patch", None)
            if callable(cm):
                return cm()
        except Exception:
            pass
        try:
            from _pydev_bundle import pydev_monkey  # type: ignore
            cm = getattr(pydev_monkey, "skip_subprocess_arg_patch", None)
            if callable(cm):
                return cm()
        except Exception:
            pass
        return nullcontext()

    def _clean_subprocess_env(self, *, pythonpath: str | None = None, minimal: bool = True) -> dict[str, str]:
        """Return a stable validation environment for generated artifacts.

        The default is intentionally minimal.  Copying the parent environment is
        not safe when the parent was launched by VS Code/debugpy, because hidden
        debugger bootstrap variables can force children to start pydevd before
        the requested ``-m py_compile`` or test command runs.
        """
        keep_names = {
            "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
            "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA",
        }
        blocked_prefixes = ("PYDEVD", "DEBUGPY", "VSCODE", "PYCHARM", "PTVSD")
        blocked_names = {
            "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONBREAKPOINT",
            "PYDEVD_LOAD_VALUES_ASYNC", "PYDEV_DEBUG", "PYDEVD_USE_FRAME_EVAL",
            "DEBUGPY_LAUNCHER_PORT", "DEBUGPY_RUNNING", "PTVSD_LAUNCHER_PORT",
            "PYDEVD_SUBPROCESS_NOTIFY", "PYDEVD_SUBPROCESS_DEBUG",
        }
        blocked_value_tokens = ("debugpy", "pydevd", ".vscode", "vscode", "pycharm", "ptvsd")
        clean: dict[str, str] = {}
        for key, value in os.environ.items():
            upper = key.upper()
            value_text = str(value or "")
            if upper in blocked_names or any(upper.startswith(prefix) for prefix in blocked_prefixes):
                continue
            if any(token in value_text.casefold() for token in blocked_value_tokens):
                continue
            if minimal and upper not in keep_names:
                continue
            clean[key] = value_text
        if pythonpath:
            clean["PYTHONPATH"] = pythonpath
        clean["PYTHONNOUSERSITE"] = "1"
        clean["PYTHONDONTWRITEBYTECODE"] = "1"
        clean["PYTHONSAFEPATH"] = "1"
        clean["PYTHONIOENCODING"] = "utf-8"
        # Defensive flags for pydevd-compatible debuggers. They are harmless
        # for normal Python processes and prevent accidental child auto-attach
        # in IDE-driven runtime validation.
        clean["PYDEVD_DISABLE_SUBPROCESS"] = "1"
        clean["PYDEVD_SUBPROCESS_NOTIFY"] = "0"
        return clean

    def _run_validation_subprocess(self, args: list[str], *, cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        command = [self._validation_python_executable(), *args]
        with self._skip_debugger_subprocess_patch():
            return subprocess.run(
                command,
                cwd=str(cwd),
                env=self._clean_subprocess_env(minimal=True),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )

    def _pip_install(self, package_name: str) -> dict[str, Any]:
        try:
            with self._skip_debugger_subprocess_patch():
                proc = subprocess.run(
                    [self._validation_python_executable(), "-I", "-m", "pip", "install", package_name],
                    env=self._clean_subprocess_env(minimal=True),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=120,
                )
            return {"returncode": proc.returncode, "stdout": proc.stdout[-3000:], "stderr": proc.stderr[-3000:]}
        except Exception as exc:
            return {"returncode": 1, "error_type": exc.__class__.__name__, "stderr": str(exc)[:2000], "stdout": ""}

    def _write_artifact(
        self,
        *,
        template: dict[str, Any],
        run_id: str,
        evidence: dict[str, Any],
        dependency_resolution: dict[str, Any],
    ) -> dict[str, Any]:
        safe_id = self._safe_name(str(template.get("template_id") or "generated_capability"))
        tool_dir = self.generated_dir / safe_id
        tool_dir.mkdir(parents=True, exist_ok=True)
        files = template.get("files") if isinstance(template.get("files"), list) else []
        written: list[str] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            rel = self._safe_relative_path(str(item.get("path") or ""))
            if not rel:
                continue
            target = tool_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            content = str(item.get("content") or "")
            target.write_text(content, encoding="utf-8")
            written.append(str(target))
        tests_dir = self.generated_tests_dir / safe_id
        tests_dir.mkdir(parents=True, exist_ok=True)
        test_files: list[str] = []
        for written_path in written:
            source_path = Path(written_path)
            if source_path.name.startswith("test_") and source_path.suffix == ".py":
                target = tests_dir / source_path.name
                target.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
                test_files.append(str(target))
        manifest = {
            "tool_id": safe_id,
            "template_id": template.get("template_id"),
            "capabilities": template.get("capabilities") if isinstance(template.get("capabilities"), list) else [],
            "source_urls": evidence.get("urls") if isinstance(evidence.get("urls"), list) else [],
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "entrypoint": template.get("entrypoint", {}),
            "dependencies": template.get("dependencies") if isinstance(template.get("dependencies"), list) else [],
            "dependency_resolution": dependency_resolution,
            "input_schema": template.get("input_schema") if isinstance(template.get("input_schema"), dict) else {},
            "output_schema": template.get("output_schema") if isinstance(template.get("output_schema"), dict) else {},
            "connection_schema": template.get("connection_schema") if isinstance(template.get("connection_schema"), dict) else {},
            "secret_schema": template.get("secret_schema") if isinstance(template.get("secret_schema"), dict) else {},
            "approval_policy": template.get("approval_policy") if isinstance(template.get("approval_policy"), dict) else {},
            "runtime_interface": template.get("runtime_interface") if isinstance(template.get("runtime_interface"), dict) else {},
            "verification_input": template.get("verification_input") if isinstance(template.get("verification_input"), dict) else {},
            "written_files": written,
            "test_dir": str(tests_dir),
            "test_files": test_files,
        }
        manifest_path = tool_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"tool_id": safe_id, "tool_dir": str(tool_dir), "test_dir": str(tests_dir), "manifest_path": str(manifest_path), "written_files": written, "test_files": test_files}

    def _validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        if not tool_dir.exists():
            return {"passed": False, "status": "failed", "reason": "artifact_directory_missing"}
        checks: list[dict[str, Any]] = []
        py_files = [str(p) for p in tool_dir.rglob("*.py")]
        if py_files:
            proc = self._run_validation_subprocess(["-I", "-m", "py_compile", *py_files], cwd=tool_dir, timeout=30)
            checks.append({"name": "python_compile", "returncode": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]})
            if proc.returncode != 0:
                return {"passed": False, "status": "failed", "checks": checks}
        test_candidates: list[Path] = []
        test_dir = Path(str(artifact.get("test_dir") or ""))
        if test_dir.exists():
            test_candidates.extend(sorted(test_dir.glob("test_*.py")))
        legacy_test_file = tool_dir / "test_tool.py"
        if legacy_test_file.exists() and legacy_test_file not in test_candidates:
            test_candidates.append(legacy_test_file)
        for test_file in test_candidates:
            runner = (
                "import runpy, sys; "
                f"sys.path.insert(0, {json.dumps(str(tool_dir))}); "
                f"runpy.run_path({json.dumps(str(test_file))}, run_name='__main__')"
            )
            proc = self._run_validation_subprocess(["-I", "-c", runner], cwd=tool_dir, timeout=30)
            check = {"name": "unit_test", "test_file": str(test_file), "returncode": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
            checks.append(check)
            self._write_test_report(artifact, check)
            if proc.returncode != 0:
                return {"passed": False, "status": "failed", "checks": checks}
        return {"passed": True, "status": "completed", "checks": checks}


    def _validate_generated_artifact_cleanliness(self, *, template: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
        """Validate that generated files only contain declared template material.

        The core cannot know business domains, so this check is structural rather
        than keyword-based.  It prevents accidental runtime pollution by checking
        that written files are inside the artifact directory, that no file is
        empty when it is an executable Python module, and that every generated
        file path was explicitly declared by the selected runtime template.
        Concrete business terms are still controlled outside ai_core by the
        runtime template registry and generated schemas.
        """
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        declared = {self._safe_relative_path(str(item.get("path") or "")) for item in (template.get("files") if isinstance(template.get("files"), list) else []) if isinstance(item, dict)}
        declared.discard("")
        checks: list[dict[str, Any]] = []
        for written in artifact.get("written_files") if isinstance(artifact.get("written_files"), list) else []:
            path = Path(str(written))
            try:
                path.relative_to(tool_dir)
            except Exception:
                checks.append({"name": "artifact_path_boundary", "passed": False, "path": str(path)})
                return {"passed": False, "status": "failed", "checks": checks}
            rel = str(path.relative_to(tool_dir))
            if rel not in declared:
                checks.append({"name": "declared_template_file", "passed": False, "path": rel})
                return {"passed": False, "status": "failed", "checks": checks}
            if path.suffix == ".py" and not path.read_text(encoding="utf-8").strip():
                checks.append({"name": "non_empty_python_module", "passed": False, "path": rel})
                return {"passed": False, "status": "failed", "checks": checks}
        checks.append({"name": "generated_artifact_cleanliness", "passed": True, "declared_file_count": len(declared)})
        return {"passed": True, "status": "completed", "checks": checks}

    def _execute_verification_run(self, *, template: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
        entrypoint = template.get("entrypoint") if isinstance(template.get("entrypoint"), dict) else {}
        module_path = Path(str(artifact.get("tool_dir") or "")) / str(entrypoint.get("module") or "tool.py")
        function_name = str(entrypoint.get("function") or "run")
        verification_input = template.get("verification_input") if isinstance(template.get("verification_input"), dict) else {}
        if not module_path.exists():
            return {"passed": False, "status": "failed", "reason": "implementation_module_missing"}
        try:
            fn = self._load_function(module_path, function_name)
            output = fn(dict(verification_input))
            expectations = template.get("verification_expectations") if isinstance(template.get("verification_expectations"), dict) else {}
            passed = self._matches_expectations(output, expectations)
            report = {
                "passed": passed,
                "status": "completed" if passed else "failed",
                "input": verification_input,
                "output": output,
                "expectations": expectations,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_verification_report(artifact, report)
            return report
        except Exception as exc:
            report = {"passed": False, "status": "failed", "error_type": exc.__class__.__name__, "error": str(exc)[:2000]}
            self._write_verification_report(artifact, report)
            return report

    def _load_function(self, path: Path, function_name: str) -> Callable[[dict[str, Any]], Any]:
        module_name = f"runtime_generated_{path.stem}_{abs(hash(str(path)))}"
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load module spec: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, function_name, None)
        if not callable(fn):
            raise RuntimeError(f"Callable '{function_name}' not found in {path}")
        return fn

    def _matches_expectations(self, output: Any, expectations: dict[str, Any]) -> bool:
        if not expectations:
            return isinstance(output, dict) and str(output.get("status") or "").lower() in {"completed", "success", "ok", "executed", ""}
        if not isinstance(output, dict):
            return False
        for key, expected in expectations.items():
            actual = output.get(key)
            if actual != expected:
                data = output.get("data") if isinstance(output.get("data"), dict) else {}
                if data.get(key) != expected:
                    return False
        return True

    def _write_test_report(self, artifact: dict[str, Any], check: dict[str, Any]) -> None:
        test_dir = Path(str(artifact.get("test_dir") or ""))
        if not test_dir.exists():
            return
        report_path = test_dir / "test_report.json"
        payload = {
            "tool_id": artifact.get("tool_id"),
            "status": "passed" if check.get("returncode") == 0 else "failed",
            "check": check,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_verification_report(self, artifact: dict[str, Any], report: dict[str, Any]) -> None:
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        if tool_dir.exists():
            (tool_dir / "verification_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        test_dir = Path(str(artifact.get("test_dir") or ""))
        if test_dir.exists():
            (test_dir / "verification_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def _register_artifact(
        self,
        *,
        template: dict[str, Any],
        artifact: dict[str, Any],
        validation: dict[str, Any],
        verification_run: dict[str, Any],
        dependency_resolution: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        RUNTIME_REGISTRY.mkdir(parents=True, exist_ok=True)
        registry = self._load_registry(self.registry_path)
        module_registry = self._load_registry(self.module_registry_path)
        tool_id = str(artifact.get("tool_id") or template.get("template_id") or "generated_capability")
        entrypoint = template.get("entrypoint") if isinstance(template.get("entrypoint"), dict) else {}
        tool_record = {
            "tool_id": tool_id,
            "name": tool_id,
            "capability": (template.get("capabilities") or [tool_id])[0] if isinstance(template.get("capabilities"), list) and template.get("capabilities") else tool_id,
            "capabilities": template.get("capabilities") if isinstance(template.get("capabilities"), list) else [tool_id],
            "status": "enabled",
            "spec_path": str(Path(str(artifact.get("tool_dir"))) / "manifest.json"),
            "implementation": {
                "type": "python_module",
                "module_path": str(Path(str(artifact.get("tool_dir"))) / str(entrypoint.get("module") or "tool.py")),
                "function": str(entrypoint.get("function") or "run"),
            },
            "dependencies": template.get("dependencies") if isinstance(template.get("dependencies"), list) else [],
            "dependency_resolution": dependency_resolution,
            "input_schema": template.get("input_schema") if isinstance(template.get("input_schema"), dict) else {},
            "output_schema": template.get("output_schema") if isinstance(template.get("output_schema"), dict) else {},
            "connection_schema": template.get("connection_schema") if isinstance(template.get("connection_schema"), dict) else {},
            "secret_schema": template.get("secret_schema") if isinstance(template.get("secret_schema"), dict) else {},
            "approval_policy": template.get("approval_policy") if isinstance(template.get("approval_policy"), dict) else {},
            "runtime_interface": template.get("runtime_interface") if isinstance(template.get("runtime_interface"), dict) else {},
            "verification": {
                "sandbox_verification": bool(validation.get("passed")),
                "execution_verification": bool(verification_run.get("passed")),
                "checks": validation.get("checks", []),
                "verification_run": verification_run,
                "test_dir": artifact.get("test_dir"),
                "test_files": artifact.get("test_files", []),
            },
            "source_urls": evidence.get("urls") if isinstance(evidence.get("urls"), list) else [],
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        module_record = {
            "module_id": tool_id,
            "name": tool_id,
            "status": "enabled",
            "source": "runtime_capability_gap_resolution",
            "runtime_generated": True,
            "module_path": tool_record["implementation"]["module_path"],
            "callable": tool_record["implementation"]["function"],
            "tool_id": tool_id,
            "capabilities": tool_record["capabilities"],
            "manifest_path": tool_record["spec_path"],
            "input_schema": tool_record.get("input_schema", {}),
            "output_schema": tool_record.get("output_schema", {}),
            "connection_schema": tool_record.get("connection_schema", {}),
            "secret_schema": tool_record.get("secret_schema", {}),
            "approval_policy": tool_record.get("approval_policy", {}),
            "runtime_interface": tool_record.get("runtime_interface", {}),
            "verification": tool_record["verification"],
            "registered_at": tool_record["registered_at"],
        }
        registry[tool_id] = tool_record
        module_registry[tool_id] = module_record
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        self.module_registry_path.write_text(json.dumps(module_registry, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "registered", "registry_path": str(self.registry_path), "module_registry_path": str(self.module_registry_path), "tool_record": tool_record, "module_record": module_record}

    def _load_registry(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in value).strip("_").lower() or "generated_capability"

    def _safe_relative_path(self, value: str) -> str:
        candidate = Path(value)
        if not value or candidate.is_absolute() or ".." in candidate.parts:
            return ""
        return str(candidate)

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED, RUNTIME_REGISTRY
from ai_core.runtime.capability.acquisition_gate import RuntimeCapabilityAcquisitionGate


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
        self.acquisition_gate = RuntimeCapabilityAcquisitionGate()

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
        pre_gate = self.acquisition_gate.evaluate_before_validation(
            requested_capability=str(template.get("template_id") or ""),
            user_input=user_input,
            template=template,
            artifact=artifact,
            dependency_resolution=dependency_resolution,
        )
        self.acquisition_gate.write_report(artifact_dir=artifact.get("tool_dir"), report={"pre_validation": pre_gate})
        capability_match = self._verify_capability_match(template=template, artifact=artifact, user_input=user_input)
        if not pre_gate.get("passed") or not capability_match.get("passed"):
            status = str(pre_gate.get("status") or "generated_but_capability_mismatch")
            return {
                "status": status,
                "template_id": template.get("template_id"),
                "score": match.score,
                "dependency_resolution": dependency_resolution,
                "artifact": artifact,
                "capability_match": capability_match,
                "acquisition_gate": pre_gate,
                "validation": None,
                "verification_run": None,
                "registration": None,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        validation = self._validate_artifact(artifact)
        verification_run: dict[str, Any] | None = None
        registration: dict[str, Any] | None = None
        registration_gate: dict[str, Any] | None = None
        if validation.get("passed"):
            verification_run = self._execute_verification_run(template=template, artifact=artifact)
        registration_gate = self.acquisition_gate.evaluate_before_registration(
            pre_validation_decision=pre_gate,
            validation=validation,
            verification_run=verification_run or {},
        )
        self.acquisition_gate.write_report(artifact_dir=artifact.get("tool_dir"), report={"pre_validation": pre_gate, "registration": registration_gate})
        if registration_gate.get("safe_to_register"):
            registration = self._register_artifact(
                template=template,
                artifact=artifact,
                validation=validation,
                verification_run=verification_run or {},
                dependency_resolution=dependency_resolution,
                evidence=evidence,
                acquisition_gate=registration_gate,
            )
            status = "implemented_tested_registered"
        else:
            status = str(registration_gate.get("status") or "generated_but_validation_failed")
        return {
            "status": status,
            "template_id": template.get("template_id"),
            "score": match.score,
            "dependency_resolution": dependency_resolution,
            "artifact": artifact if 'artifact' in locals() else None,
            "capability_match": capability_match if 'capability_match' in locals() else None,
            "acquisition_gate": registration_gate if 'registration_gate' in locals() else pre_gate if 'pre_gate' in locals() else None,
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
            # Template selection remains contract-driven.  A template may declare
            # a numeric priority to prefer a precise capability template over a
            # broader fallback template when both match the same request.
            try:
                score += int(template.get("selection_priority") or 0)
            except Exception:
                pass
            if required:
                score += len(required) * 10
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

    def _clean_subprocess_env(self, *, pythonpath: str | None = None) -> dict[str, str]:
        """Return a stable validation environment for generated artifacts.

        VS Code/debugpy and similar launchers can inject PYTHONPATH, pydevd,
        or debugger bootstrap variables into child Python processes.  Generated
        capability validation must be isolated from the IDE runtime; otherwise
        a valid generated tool may fail before its own code is even compiled.
        """
        blocked_prefixes = ("PYDEVD", "DEBUGPY", "VSCODE", "PYCHARM")
        blocked_names = {
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONSTARTUP",
            "PYTHONBREAKPOINT",
            "PYDEVD_LOAD_VALUES_ASYNC",
        }
        clean: dict[str, str] = {}
        for key, value in os.environ.items():
            upper = key.upper()
            if upper in blocked_names or any(upper.startswith(prefix) for prefix in blocked_prefixes):
                continue
            clean[key] = value
        if pythonpath:
            clean["PYTHONPATH"] = pythonpath
        clean.setdefault("PYTHONNOUSERSITE", "1")
        clean.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        return clean

    def _python_executable_candidates(self) -> list[str]:
        """Return Python executables suitable for sandbox validation.

        The active process may be launched under an IDE/debugger wrapper.  For
        generated capability validation we prefer the base interpreter and fall
        back to common launcher names.  Duplicates are removed while preserving
        order.
        """
        candidates: list[str] = []
        base_executable = getattr(sys, "_base_executable", None)
        for item in [base_executable, sys.executable, "python", "python3"]:
            value = str(item or "").strip()
            if value and value not in candidates:
                candidates.append(value)
        return candidates

    def _run_isolated_python(self, args: list[str], *, cwd: Path, timeout: int = 30, pythonpath: str | None = None) -> dict[str, Any]:
        """Run a generated-artifact validation command with debugger isolation.

        A failure caused by debugger bootstrap, not by generated code, should
        not be treated as a capability validation failure until every candidate
        interpreter has been tried.  The returned payload keeps every attempt so
        the devil-checker can distinguish a real implementation failure from an
        environment failure.
        """
        attempts: list[dict[str, Any]] = []
        for exe in self._python_executable_candidates():
            try:
                proc = subprocess.run(
                    [exe, "-I", *args],
                    cwd=str(cwd),
                    env=self._clean_subprocess_env(pythonpath=pythonpath),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                )
                attempt = {
                    "executable": exe,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout[-2000:],
                    "stderr": proc.stderr[-2000:],
                }
                attempts.append(attempt)
                if proc.returncode == 0:
                    return {**attempt, "attempts": attempts}
                stderr_l = (proc.stderr or "").casefold()
                environment_failure = any(
                    marker in stderr_l
                    for marker in ["debugpy", "pydevd", "keyboardinterrupt", "_bz2", "pythonhome", "pythonpath"]
                )
                if not environment_failure:
                    return {**attempt, "attempts": attempts}
            except Exception as exc:
                attempts.append({"executable": exe, "returncode": -1, "stdout": "", "stderr": f"{exc.__class__.__name__}: {exc}"})
                continue
        last = attempts[-1] if attempts else {"executable": "", "returncode": -1, "stdout": "", "stderr": "no_python_executable_available"}
        return {**last, "attempts": attempts}

    def _pip_install(self, package_name: str) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", package_name],
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


    def _verify_capability_match(self, *, template: dict[str, Any], artifact: dict[str, Any], user_input: str) -> dict[str, Any]:
        """Verify that the generated artifact really implements the matched capability.

        This is intentionally contract-driven. ai_core does not know concrete
        capability domains. A runtime template may declare
        marker strings that must appear in generated files/schemas before the
        artifact is allowed to proceed to sandbox validation and registration.
        """
        contract = template.get("capability_match_contract") if isinstance(template.get("capability_match_contract"), dict) else {}
        if not contract:
            return {"passed": True, "status": "not_required", "checks": []}
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        checks: list[dict[str, Any]] = []
        combined_parts: list[str] = [str(template.get("template_id") or ""), str(template.get("description") or ""), user_input or ""]
        if tool_dir.exists():
            for path in sorted(tool_dir.rglob("*")):
                if path.name in {"capability_match_report.json", "acquisition_gate_report.json", "verification_report.json", "test_report.json"}:
                    continue
                if path.is_file() and path.suffix.lower() in {".py", ".json", ".md", ".txt", ".yaml", ".yml"}:
                    try:
                        text = path.read_text(encoding="utf-8", errors="ignore")
                        if path.name == "manifest.json":
                            try:
                                payload = json.loads(text or "{}")
                                if isinstance(payload, dict):
                                    payload.pop("capability_match_contract", None)
                                    text = json.dumps(payload, ensure_ascii=False)
                            except Exception:
                                pass
                        combined_parts.append(text)
                    except Exception:
                        continue
        combined = "\n".join(combined_parts).casefold()
        required_markers = contract.get("required_markers") if isinstance(contract.get("required_markers"), list) else []
        forbidden_markers = contract.get("forbidden_markers") if isinstance(contract.get("forbidden_markers"), list) else []
        missing = [str(marker) for marker in required_markers if str(marker).casefold() not in combined]
        present_forbidden = [str(marker) for marker in forbidden_markers if str(marker).casefold() in combined]
        checks.append({"name": "required_markers", "passed": not missing, "missing": missing})
        checks.append({"name": "forbidden_markers", "passed": not present_forbidden, "present": present_forbidden})
        passed = not missing and not present_forbidden
        report = {
            "passed": passed,
            "status": "completed" if passed else "failed",
            "checks": checks,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if tool_dir.exists():
            (tool_dir / "capability_match_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def _validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        if not tool_dir.exists():
            return {"passed": False, "status": "failed", "reason": "artifact_directory_missing"}
        checks: list[dict[str, Any]] = []
        py_files = [str(p) for p in tool_dir.rglob("*.py")]
        if py_files:
            proc = self._run_isolated_python(["-m", "py_compile", *py_files], cwd=tool_dir, timeout=30)
            checks.append({
                "name": "python_compile",
                "returncode": proc.get("returncode"),
                "stdout": str(proc.get("stdout") or "")[-2000:],
                "stderr": str(proc.get("stderr") or "")[-2000:],
                "attempts": proc.get("attempts", []),
            })
            if proc.get("returncode") != 0:
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
            proc = self._run_isolated_python(["-c", runner], cwd=tool_dir, timeout=30)
            check = {
                "name": "unit_test",
                "test_file": str(test_file),
                "returncode": proc.get("returncode"),
                "stdout": str(proc.get("stdout") or "")[-2000:],
                "stderr": str(proc.get("stderr") or "")[-2000:],
                "attempts": proc.get("attempts", []),
            }
            checks.append(check)
            self._write_test_report(artifact, check)
            if proc.get("returncode") != 0:
                return {"passed": False, "status": "failed", "checks": checks}
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
        acquisition_gate: dict[str, Any] | None = None,
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
                "registration_gate": acquisition_gate or {},
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

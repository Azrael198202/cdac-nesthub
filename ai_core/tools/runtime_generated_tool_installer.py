from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_REGISTRY
from ai_core.tools.runtime_tool_artifact_validator import RuntimeToolArtifactValidator
from ai_core.runtime.capability.acquisition_gate import RuntimeCapabilityAcquisitionGate
from ai_core.sandbox.verified_sandbox_runtime import VerifiedSandboxRuntime


class RuntimeGeneratedToolInstaller:
    """
    Installs runtime-generated tool artifacts into runtime/generated/tools.

    This installer is intentionally generic. It does not know what a tool does,
    how a capability should work, or which external API should be used.

    The artifact is expected to be produced by the runtime intelligence layer
    such as an LLM/code-generation step or a human-reviewed code artifact.
    """

    def __init__(self) -> None:
        self.tools_dir = RUNTIME_GENERATED / "tools"
        self.registry_path = RUNTIME_REGISTRY / "tool_registry.json"
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        RUNTIME_REGISTRY.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self.registry_path.write_text("{}", encoding="utf-8")
        self.validator = RuntimeToolArtifactValidator()
        self.acquisition_gate = RuntimeCapabilityAcquisitionGate()
        self.sandbox_runtime = VerifiedSandboxRuntime()

    def install_from_step(
        self,
        *,
        capability: str,
        step: dict[str, Any],
        user_input: str = "",
    ) -> dict[str, Any] | None:
        artifact = self._extract_artifact(step)
        if not artifact:
            return None
        return self.install_artifact(
            artifact=artifact,
            capability=capability,
            source_step=step,
            user_input=user_input,
        )

    def install_artifact(
        self,
        *,
        artifact: dict[str, Any],
        capability: str,
        source_step: dict[str, Any] | None = None,
        user_input: str = "",
    ) -> dict[str, Any]:
        tool_id = self._safe_name(str(artifact.get("tool_id") or f"generated_{capability}"))
        target_dir = self.tools_dir / tool_id
        target_dir.mkdir(parents=True, exist_ok=True)

        files = artifact.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("Runtime tool artifact must contain a non-empty files object.")

        written_files: dict[str, str] = {}
        for relative_name, content in files.items():
            path = self._safe_child_path(target_dir, str(relative_name))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
            written_files[str(relative_name)] = str(path)

        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        manifest = dict(manifest)
        manifest.setdefault("tool_id", tool_id)
        manifest.setdefault("name", tool_id)
        manifest.setdefault("capability", capability)
        manifest.setdefault("capabilities", [capability])
        manifest.setdefault("status", "enabled")
        manifest.setdefault("created_at", datetime.utcnow().isoformat())
        manifest.setdefault("runtime_generated", True)
        manifest.setdefault("source", "runtime_generated_artifact")
        manifest.setdefault("source_user_input", user_input)
        manifest.setdefault("source_step", source_step or {})
        manifest.setdefault("input_schema", {"type": "object", "additionalProperties": True})
        manifest.setdefault("output_schema", {"type": "object", "additionalProperties": True})
        manifest.setdefault("safety", {
            "can_read_external_data": "runtime_declared",
            "can_write_external_data": False,
            "can_perform_irreversible_action": False,
            "requires_human_confirmation": bool((source_step or {}).get("requires_human_confirmation", False)),
            "generated_code_must_be_reviewed": bool(artifact.get("requires_review", False)),
        })
        manifest.setdefault("execution_claims", {
            "real_execution": artifact.get("real_execution"),
            "no_mock_data": artifact.get("no_mock_data"),
            "uses_network": artifact.get("uses_network"),
            "generated_by_runtime": True,
            "live_verification_required": True if artifact.get("uses_network") else False,
            "live_verification_passed": bool((artifact.get("verification") or {}).get("live_verification_passed")),
        })
        if artifact.get("verification") and "verification" not in manifest:
            manifest["verification"] = artifact.get("verification")
        if artifact.get("api_discovery") and "api_discovery" not in manifest:
            manifest["api_discovery"] = artifact.get("api_discovery")
        if artifact.get("documentation_understanding") and "documentation_understanding" not in manifest:
            manifest["documentation_understanding"] = artifact.get("documentation_understanding")
        if artifact.get("parameter_mapping") and "parameter_mapping" not in manifest:
            manifest["parameter_mapping"] = artifact.get("parameter_mapping")

        implementation = manifest.setdefault("implementation", {})
        if not isinstance(implementation, dict):
            implementation = {}
            manifest["implementation"] = implementation
        implementation.setdefault("type", "python_function")
        implementation.setdefault("function", "run")
        module_path = implementation.get("module_path") or implementation.get("path") or "tool.py"
        module_file_name = Path(str(module_path)).name
        if module_file_name not in {Path(name).name for name in written_files.keys()}:
            # Fall back to the first written file if the manifest did not match.
            module_file_name = Path(next(iter(written_files.values()))).name
        implementation["module_path"] = str(target_dir / module_file_name)

        module_path_for_validation = Path(str(implementation.get("module_path")))
        callable_name = str(implementation.get("function") or implementation.get("callable") or "run")
        validation = self.validator.validate_python_file(module_path_for_validation, callable_name=callable_name)
        if not validation.get("valid"):
            raise ValueError("Generated runtime tool artifact failed validation: " + "; ".join(validation.get("errors", [])))

        sandbox_artifact = self._build_sandbox_artifact(
            target_dir=target_dir,
            written_files=written_files,
            manifest=manifest,
            callable_name=callable_name,
            module_file_name=module_file_name,
            source_artifact=artifact,
            capability=capability,
            user_input=user_input,
        )
        pre_gate = self.acquisition_gate.evaluate_before_validation(
            requested_capability=capability,
            user_input=user_input,
            template={},
            artifact=sandbox_artifact,
            dependency_resolution={"passed": True, "status": "installer_prechecked"},
        )
        if not pre_gate.get("passed"):
            self.acquisition_gate.write_report(artifact_dir=target_dir, report={"pre_validation": pre_gate})
            raise ValueError("Generated runtime tool artifact failed acquisition gate: " + str(pre_gate.get("reason")))

        sandbox_result = self.sandbox_runtime.verify_tool_artifact(
            artifact=sandbox_artifact,
            test_input=self._verification_input(manifest=manifest, artifact=artifact),
            allow_network=bool(artifact.get("uses_network") and artifact.get("allow_network_verification")),
            timeout_seconds=int(artifact.get("verification_timeout_seconds") or 60),
        )
        registration_gate = self.acquisition_gate.evaluate_before_registration(
            pre_validation_decision=pre_gate,
            validation={"passed": bool(sandbox_result.get("safe_to_register")), "mode": sandbox_result.get("mode"), "checks": sandbox_result.get("checks", [])},
            verification_run={"passed": bool(sandbox_result.get("safe_to_register")), "sandbox_result": sandbox_result},
            sandbox_result=sandbox_result,
        )
        self.acquisition_gate.write_report(artifact_dir=target_dir, report={"pre_validation": pre_gate, "sandbox": sandbox_result, "registration": registration_gate})
        if not registration_gate.get("safe_to_register"):
            raise ValueError("Generated runtime tool artifact blocked before registry enablement: " + str(registration_gate.get("reason")))

        manifest["verification"] = {
            **(manifest.get("verification") if isinstance(manifest.get("verification"), dict) else {}),
            "sandbox_verification": True,
            "execution_verification": True,
            "registration_gate": registration_gate,
            "sandbox_result": sandbox_result,
        }

        manifest_path = target_dir / "tool.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        registry = self._load_registry()
        registry[tool_id] = {
            "tool_id": tool_id,
            "name": manifest.get("name", tool_id),
            "capability": manifest.get("capability", capability),
            "capabilities": manifest.get("capabilities", [capability]),
            "status": manifest.get("status", "enabled"),
            "spec_path": str(manifest_path),
            "implementation": manifest.get("implementation", {}),
            "input_schema": manifest.get("input_schema", {"type": "object", "additionalProperties": True}),
            "output_schema": manifest.get("output_schema", {"type": "object", "additionalProperties": True}),
            "safety": manifest.get("safety", {}),
            "runtime_generated": True,
            "source": manifest.get("source"),
            "execution_claims": manifest.get("execution_claims", {}),
            "network": manifest.get("network", {}),
            "api_discovery": manifest.get("api_discovery", {}),
            "documentation_understanding": manifest.get("documentation_understanding", {}),
            "parameter_mapping": manifest.get("parameter_mapping", {}),
            "runtime_execution_policy": manifest.get("runtime_execution_policy", {}) if isinstance(manifest.get("runtime_execution_policy"), dict) else {},
            "verification": manifest.get("verification", {}),
        }
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        return registry[tool_id]

    def _build_sandbox_artifact(
        self,
        *,
        target_dir: Path,
        written_files: dict[str, str],
        manifest: dict[str, Any],
        callable_name: str,
        module_file_name: str,
        source_artifact: dict[str, Any],
        capability: str,
        user_input: str,
    ) -> dict[str, Any]:
        files: dict[str, str] = {}
        for relative_name, absolute_path in written_files.items():
            path = Path(absolute_path)
            if path.exists():
                files[str(relative_name)] = path.read_text(encoding="utf-8", errors="ignore")
        sandbox_manifest = dict(manifest)
        sandbox_manifest["implementation"] = {"module_path": module_file_name, "function": callable_name}
        if isinstance(source_artifact.get("capability_match_contract"), dict):
            sandbox_manifest["capability_match_contract"] = source_artifact.get("capability_match_contract")
        return {
            "tool_id": manifest.get("tool_id"),
            "capability": capability,
            "manifest": sandbox_manifest,
            "files": files,
            "artifact_dir": str(target_dir),
            "source_user_input": user_input,
            "capability_match_contract": source_artifact.get("capability_match_contract") if isinstance(source_artifact.get("capability_match_contract"), dict) else None,
        }

    def _verification_input(self, *, manifest: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
        for source in (artifact, manifest):
            value = source.get("verification_input") if isinstance(source, dict) else None
            if isinstance(value, dict):
                return value
        return {}

    def _extract_artifact(self, step: dict[str, Any]) -> dict[str, Any] | None:
        for key in [
            "runtime_tool_generation",
            "runtime_generated_tool",
            "tool_generation_artifact",
            "generated_tool_artifact",
        ]:
            value = step.get(key)
            if isinstance(value, dict):
                return value
        return None

    def _load_registry(self) -> dict[str, Any]:
        try:
            return json.loads(self.registry_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def _safe_child_path(self, base_dir: Path, relative_name: str) -> Path:
        pure = PurePosixPath(relative_name.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"Unsafe runtime tool file path: {relative_name}")
        return base_dir / Path(*pure.parts)

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in value).strip("_").lower() or "runtime_tool"

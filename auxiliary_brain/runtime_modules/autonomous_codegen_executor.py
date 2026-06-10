from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_KNOWLEDGE
from ai_core.events.event_bus import event_bus
from auxiliary_brain.runtime_modules.module_artifact_generator import RuntimeModuleArtifactGenerator
from auxiliary_brain.runtime_modules.runtime_generated_module_installer import RuntimeGeneratedModuleInstaller
from auxiliary_brain.runtime_modules.module_loader import RuntimeModuleLoader
from auxiliary_brain.sandbox.verified_sandbox_runtime import VerifiedSandboxRuntime
from ai_core.utils.safe_json import safe_json_dumps


class AutonomousCodegenExecutor:
    """Autonomous runtime code-generation executor.

    This class closes the generic runtime loop:

    pending codegen request -> strong-model artifact generation -> sandbox test
    -> registry enable -> executable runtime module.

    It is intentionally capability-agnostic. It never branches on domain words;
    it only uses structured request metadata, artifact manifests, sandbox output,
    and registry records.
    """

    def __init__(self) -> None:
        self.requests_dir = RUNTIME_GENERATED / "module_generation_requests"
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_generator = RuntimeModuleArtifactGenerator()
        self.installer = RuntimeGeneratedModuleInstaller()
        self.loader = RuntimeModuleLoader()
        self.sandbox = VerifiedSandboxRuntime()
        self.knowledge_path = RUNTIME_KNOWLEDGE / "successful_runtime_codegen.jsonl"
        self.knowledge_path.parent.mkdir(parents=True, exist_ok=True)

    async def execute_request_file(
        self,
        *,
        request_path: str | Path,
        run_id: str,
        node_id: str,
        step_id: str,
        test_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = Path(request_path)
        if not path.exists():
            return {
                "status": "codegen_request_not_found",
                "request_path": str(path),
                "enabled": False,
            }
        request = json.loads(path.read_text(encoding="utf-8") or "{}")
        return await self.execute_request(
            request=request,
            request_path=path,
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            test_input=test_input,
        )

    async def execute_request(
        self,
        *,
        request: dict[str, Any],
        request_path: str | Path | None = None,
        run_id: str,
        node_id: str,
        step_id: str,
        test_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(request, dict):
            return {"status": "invalid_codegen_request", "enabled": False}

        request_id = str(request.get("request_id") or "runtime_codegen_request")
        capability = str(request.get("capability") or "runtime_capability")
        module_id = str(request.get("module_id") or f"module_{self._safe_name(capability)}")

        await event_bus.emit(run_id, {
            "type": "AUTONOMOUS_CODEGEN_STARTED",
            "title": "Autonomous code generation started",
            "message": f"Generating module implementation for request={request_id}",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"request_id": request_id, "module_id": module_id, "capability": capability},
        })

        generation_request = self._to_generation_request(request)
        try:
            artifact = await self.artifact_generator.generate_artifact(
                run_id=run_id,
                node_id=node_id,
                generation_request=generation_request,
            )
        except Exception as exc:
            self._mark_request(path=request_path, status="strong_model_generation_failed", error=str(exc))
            await event_bus.emit(run_id, {
                "type": "AUTONOMOUS_CODEGEN_MODEL_FAILED",
                "title": "Autonomous code generation model failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
            return {
                "status": "strong_model_generation_failed",
                "enabled": False,
                "request_id": request_id,
                "module_id": module_id,
                "capability": capability,
                "error": {"message": str(exc)},
            }

        if not isinstance(artifact, dict) or not isinstance(artifact.get("files"), dict) or not artifact.get("files"):
            self._mark_request(path=request_path, status="artifact_invalid", error="Artifact contains no files.")
            return {
                "status": "artifact_invalid",
                "enabled": False,
                "request_id": request_id,
                "module_id": module_id,
                "capability": capability,
                "artifact": artifact,
            }

        artifact.setdefault("module_id", module_id)
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        manifest.setdefault("module_id", module_id)
        manifest.setdefault("capability", capability)
        manifest.setdefault("capabilities", [capability])
        manifest.setdefault("runtime_interface", self._default_runtime_interface())
        manifest.setdefault("input_schema", self._default_input_schema())
        manifest.setdefault("output_schema", self._default_output_schema())
        manifest.setdefault("safety_policy", self._default_safety_policy())
        manifest.setdefault("execution_claims", {})
        artifact["manifest"] = manifest

        verification = self.sandbox.verify_module_artifact(
            artifact=artifact,
            test_input=test_input or self._default_test_input(request),
            allow_network=self._uses_network(artifact),
        )
        artifact.setdefault("verification", {})["sandbox_verification"] = verification

        await event_bus.emit(run_id, {
            "type": "AUTONOMOUS_CODEGEN_SANDBOX_RESULT",
            "title": "Autonomous codegen sandbox result",
            "message": verification.get("reason", "Sandbox verification completed."),
            "node_id": node_id,
            "step_id": step_id,
            "result": verification,
        })

        if not verification.get("safe_to_register") and verification.get("status") != "passed":
            self._mark_request(path=request_path, status="sandbox_validation_failed", error=verification.get("reason"))
            return {
                "status": "sandbox_validation_failed",
                "enabled": False,
                "request_id": request_id,
                "module_id": module_id,
                "capability": capability,
                "verification": verification,
            }

        installed = self.installer.install_artifact(
            artifact=artifact,
            capability=capability,
            source_step=self._source_step(request),
            user_input=str(request.get("source_user_input") or ""),
        )
        self._mark_request(path=request_path, status="enabled", registry_record=installed)

        record = {
            "status": "enabled",
            "enabled": True,
            "request_id": request_id,
            "module_id": installed.get("module_id") or module_id,
            "capability": capability,
            "registry_record": installed,
            "verification": verification,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._write_success_knowledge(record)

        await event_bus.emit(run_id, {
            "type": "AUTONOMOUS_CODEGEN_ENABLED",
            "title": "Autonomous codegen enabled module",
            "message": f"Generated module enabled for capability={capability}",
            "node_id": node_id,
            "step_id": step_id,
            "result": record,
        })
        return record

    async def execute_latest_pending_for_capability(
        self,
        *,
        capability: str,
        run_id: str,
        node_id: str,
        step_id: str,
        test_input: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        requests = self.find_pending_requests(capability=capability)
        if not requests:
            return None
        return await self.execute_request_file(
            request_path=requests[-1],
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            test_input=test_input,
        )

    def find_pending_requests(self, *, capability: str | None = None) -> list[Path]:
        paths = sorted(self.requests_dir.glob("*.json"))
        matches: list[Path] = []
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except json.JSONDecodeError:
                continue
            status = str(data.get("status") or "").lower()
            if status not in {"pending_strong_model_generation", "pending", "retry"}:
                continue
            if capability and str(data.get("capability") or "") != capability:
                continue
            matches.append(path)
        return matches

    def _to_generation_request(self, request: dict[str, Any]) -> dict[str, Any]:
        blueprint = request.get("blueprint") if isinstance(request.get("blueprint"), dict) else {}
        return {
            "request_type": "autonomous_runtime_module_codegen",
            "request_id": request.get("request_id"),
            "module_id": request.get("module_id"),
            "capability": request.get("capability"),
            "source_user_input": request.get("source_user_input"),
            "blueprint": blueprint,
            "source_step": blueprint.get("source_step") if isinstance(blueprint.get("source_step"), dict) else {},
            "model_task": request.get("model_task") if isinstance(request.get("model_task"), dict) else {},
            "safety_requirements": request.get("safety_requirements") if isinstance(request.get("safety_requirements"), list) else [],
            "constraints": {
                "must_define_runtime_interface": ["validate_config", "health_check", "run"],
                "must_define_entrypoint_signature": "def run(payload: dict) -> dict",
                "entrypoint_result_must_be_json_serializable_dict": True,
                "must_return_schema_compatible_output": True,
                "must_not_log_secrets": True,
                "must_not_perform_irreversible_actions_without_confirmation": True,
                "must_be_sandbox_testable": True,
                "must_generate_module_py": True,
                "must_not_emit_explanatory_text": True,
                "must_be_reusable_across_runtime_parameters": True,
                "must_not_hardcode_user_specific_location_or_date": True,
                "must_read_location_date_and_other_inputs_from_payload": True,
            },
            "expected_contract": {
                "module_id": "string",
                "manifest": "module.json compatible object",
                "files": {"module.py": "python source code containing def run(payload: dict) -> dict"},
            },
        }

    def _default_test_input(self, request: dict[str, Any]) -> dict[str, Any]:
        blueprint = request.get("blueprint") if isinstance(request.get("blueprint"), dict) else {}
        source_step = blueprint.get("source_step") if isinstance(blueprint.get("source_step"), dict) else {}
        params = source_step.get("parameters") if isinstance(source_step.get("parameters"), dict) else {}
        return {
            "parameters": params,
            "known": params.get("known") if isinstance(params.get("known"), dict) else {},
            "optional": params.get("optional") if isinstance(params.get("optional"), dict) else {},
            "context": {
                "request_id": request.get("request_id"),
                "module_id": request.get("module_id"),
            },
            "source_step": source_step,
        }

    def _source_step(self, request: dict[str, Any]) -> dict[str, Any]:
        blueprint = request.get("blueprint") if isinstance(request.get("blueprint"), dict) else {}
        value = blueprint.get("source_step")
        return value if isinstance(value, dict) else {}

    def _uses_network(self, artifact: dict[str, Any]) -> bool:
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        claims = manifest.get("execution_claims") if isinstance(manifest.get("execution_claims"), dict) else {}
        return bool(claims.get("uses_network") or artifact.get("uses_network"))

    def _mark_request(
        self,
        *,
        path: str | Path | None,
        status: str,
        error: str | None = None,
        registry_record: dict[str, Any] | None = None,
    ) -> None:
        if not path:
            return
        request_path = Path(path)
        if not request_path.exists():
            return
        try:
            data = json.loads(request_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return
        data["status"] = status
        data["updated_at"] = datetime.utcnow().isoformat()
        if error:
            data["last_error"] = error
        if registry_record:
            data["registry_record"] = registry_record
        request_path.write_text(safe_json_dumps(data, indent=2), encoding="utf-8")

    def _write_success_knowledge(self, record: dict[str, Any]) -> None:
        with self.knowledge_path.open("a", encoding="utf-8") as f:
            f.write(safe_json_dumps(record) + "\n")

    def _default_runtime_interface(self) -> dict[str, Any]:
        return {"functions": [{"name": "validate_config"}, {"name": "health_check"}, {"name": "run"}], "entrypoint": "module.py"}

    def _default_input_schema(self) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": True}

    def _default_output_schema(self) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": True}

    def _default_safety_policy(self) -> dict[str, Any]:
        return {
            "requires_review_before_enable": False,
            "can_perform_irreversible_action": False,
            "requires_human_confirmation_before_irreversible_action": True,
        }

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in str(value)).strip("_").lower() or "module"

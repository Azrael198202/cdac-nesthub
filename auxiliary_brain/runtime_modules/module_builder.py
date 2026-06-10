from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED
from auxiliary_brain.runtime_modules.module_codegen_request import ModuleCodeGenerationRequestBuilder
from auxiliary_brain.runtime_modules.module_registry import RuntimeModuleRegistry


class RuntimeModuleBuilder:
    """
    Generic runtime module builder.

    IMPORTANT:
    This builder does not understand domain-specific module types.
    It only creates a module package from structured runtime metadata.

    Semantic understanding must happen before this step:
      user input -> LLM/runtime planning -> structured module_blueprint metadata

    ai_core responsibility:
      - create module folder
      - write module.json
      - write safe placeholder module.py
      - write test input
      - write codegen request
      - register module as blueprint/generated
    """

    def __init__(self) -> None:
        self.modules_dir = RUNTIME_GENERATED / "modules"
        self.modules_dir.mkdir(parents=True, exist_ok=True)
        self.registry = RuntimeModuleRegistry()
        self.codegen = ModuleCodeGenerationRequestBuilder()

    def ensure_module_for_capability(
        self,
        *,
        capability: str,
        source_step: dict[str, Any] | None = None,
        user_input: str = "",
        module_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.registry.find_by_capability(capability)
        if existing:
            return {
                "status": "module_already_registered",
                "module": existing,
            }

        return self.create_module_blueprint(
            capability=capability,
            source_step=source_step or {},
            user_input=user_input,
            module_metadata=module_metadata or self._extract_metadata(source_step or {}),
        )

    def create_module_blueprint(
        self,
        *,
        capability: str,
        source_step: dict[str, Any],
        user_input: str = "",
        module_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        module_metadata = module_metadata or {}
        module_id = module_metadata.get("module_id") or f"module_{self._safe_name(capability)}"
        module_dir = self.modules_dir / module_id
        module_dir.mkdir(parents=True, exist_ok=True)

        blueprint = {
            "module_id": module_id,
            "capability": capability,
            "status": "blueprint_generated",
            "created_at": datetime.utcnow().isoformat(),
            "source_user_input": user_input,
            "source_step": source_step,
            "module_metadata": module_metadata,
            "input_schema": module_metadata.get("input_schema", self._default_input_schema()),
            "output_schema": module_metadata.get("output_schema", self._default_output_schema()),
            "runtime_interface": module_metadata.get("runtime_interface", self._default_runtime_interface()),
            "safety_policy": module_metadata.get("safety_policy", self._default_safety_policy()),
            "implementation_plan": module_metadata.get("implementation_plan", self._default_implementation_plan()),
            "notes": [
                "This module is generated as a blueprint only.",
                "Domain-specific logic must come from runtime-generated metadata, not ai_core.",
                "Generated implementation must be reviewed before enabling execution.",
            ],
        }

        (module_dir / "module.json").write_text(json.dumps(blueprint, ensure_ascii=False, indent=2), encoding="utf-8")
        (module_dir / "module.py").write_text(self._placeholder_module_py(module_id), encoding="utf-8")
        (module_dir / "README.md").write_text(self._readme(module_id, capability), encoding="utf-8")
        (module_dir / "test_input.json").write_text(json.dumps(module_metadata.get("test_input", {}), ensure_ascii=False, indent=2), encoding="utf-8")

        codegen_request = self.codegen.create_request(
            module_id=module_id,
            capability=capability,
            blueprint=blueprint,
            user_input=user_input,
        )

        record = self.registry.register(
            module_id=module_id,
            capability=capability,
            module_dir=module_dir,
            status="blueprint_generated",
            metadata={
                "codegen_request_path": codegen_request.get("request_path"),
                "source": "runtime_module_builder",
            },
        )

        return {
            "status": "module_blueprint_generated",
            "module_id": module_id,
            "module_dir": str(module_dir),
            "blueprint": blueprint,
            "codegen_request": codegen_request,
            "registry_record": record,
        }

    def _extract_metadata(self, source_step: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(source_step, dict):
            return {}

        for key in ["module_blueprint", "module_metadata", "runtime_module", "runtime_metadata", "metadata"]:
            value = source_step.get(key)
            if isinstance(value, dict):
                return value

        params = source_step.get("parameters")
        if isinstance(params, dict):
            for key in ["module_blueprint", "module_metadata", "runtime_module", "runtime_metadata", "metadata"]:
                value = params.get(key)
                if isinstance(value, dict):
                    return value

        return {}

    def _default_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "config": {"type": "object"},
                "context": {"type": "object"},
                "payload": {"type": "object"},
            },
            "additionalProperties": True,
        }

    def _default_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "data": {"type": "object"},
                "events": {"type": "array"},
                "requires_human_confirmation": {"type": "boolean"},
            },
            "additionalProperties": True,
        }

    def _default_runtime_interface(self) -> dict[str, Any]:
        return {
            "functions": [
                {"name": "validate_config", "type": "sync"},
                {"name": "run", "type": "sync_or_async"},
                {"name": "health_check", "type": "sync"},
            ],
            "entrypoint": "module.py",
        }

    def _default_safety_policy(self) -> dict[str, Any]:
        return {
            "requires_review_before_enable": True,
            "can_access_external_systems": "runtime_decides",
            "can_perform_irreversible_action": False,
            "requires_human_confirmation_before_irreversible_action": True,
            "policy_source": "generic_core_default",
        }

    def _default_implementation_plan(self) -> list[str]:
        return [
            "Use runtime-generated module metadata.",
            "Generate implementation outside ai_core.",
            "Generate tests.",
            "Run validation and safety review.",
            "Register module as enabled only after approval.",
        ]

    def _placeholder_module_py(self, module_id: str) -> str:
        return (
            f'"""Runtime generated placeholder module: {module_id}."""\n\n'
            "from typing import Any\n\n\n"
            "def validate_config(config: dict[str, Any]) -> dict[str, Any]:\n"
            "    return {\"valid\": False, \"reason\": \"Module implementation is not generated or approved yet.\"}\n\n\n"
            "def health_check() -> dict[str, Any]:\n"
            "    return {\"status\": \"blueprint_only\"}\n\n\n"
            "def run(input_data: dict[str, Any]) -> dict[str, Any]:\n"
            "    return {\n"
            '        \"status\": \"not_implemented\",\n'
            f'        \"module_id\": \"{module_id}\",\n'
            '        \"message\": \"Module blueprint exists, but implementation has not been generated or approved.\",\n'
            '        \"data\": {},\n'
            '        \"requires_human_confirmation\": True,\n'
            "    }\n"
        )

    def _readme(self, module_id: str, capability: str) -> str:
        return (
            f"# {module_id}\n\n"
            "Runtime-generated module blueprint.\n\n"
            f"Capability: `{capability}`\n\n"
            "This module is not enabled until implementation is generated and approved.\n"
        )

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in str(value)).strip("_").lower() or "module"

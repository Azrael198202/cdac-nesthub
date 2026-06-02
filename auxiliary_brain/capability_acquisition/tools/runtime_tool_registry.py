from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_REGISTRY
from auxiliary_brain.capability_acquisition.tools.tool_blueprint_builder import ToolBlueprintBuilder
from auxiliary_brain.capability_acquisition.tools.browser_automation_blueprint import BrowserAutomationBlueprintBuilder
from auxiliary_brain.capability_acquisition.tools.tool_code_generation_request import ToolCodeGenerationRequestBuilder
from auxiliary_brain.capability_acquisition.tools.runtime_generated_tool_installer import RuntimeGeneratedToolInstaller
from auxiliary_brain.capability_acquisition.tools.runtime_primitive_tool_factory import RuntimePrimitiveToolFactory


class RuntimeToolRegistry:
    """
    Generic runtime tool registry.

    ai_core does not know business tools.
    It only knows how to read/write generic tool specs.
    """

    def __init__(self) -> None:
        self.generated_tools_dir = RUNTIME_GENERATED / "tools"
        self.registry_path = RUNTIME_REGISTRY / "tool_registry.json"
        self.generated_tools_dir.mkdir(parents=True, exist_ok=True)
        RUNTIME_REGISTRY.mkdir(parents=True, exist_ok=True)

        if not self.registry_path.exists():
            self.registry_path.write_text("{}", encoding="utf-8")

        self.generated_tool_installer = RuntimeGeneratedToolInstaller()
        self.primitive_tool_factory = RuntimePrimitiveToolFactory()

        self.blueprint_builder = ToolBlueprintBuilder()
        self.browser_blueprint_builder = BrowserAutomationBlueprintBuilder()
        self.codegen_request_builder = ToolCodeGenerationRequestBuilder()

    def load_registry(self) -> dict[str, Any]:
        try:
            return json.loads(self.registry_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def save_registry(self, data: dict[str, Any]) -> None:
        self.registry_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def find_by_capability(self, capability: str) -> dict[str, Any] | None:
        registry = self.load_registry()
        matches: list[dict[str, Any]] = []
        for tool in registry.values():
            if capability in tool.get("capabilities", []) or tool.get("capability") == capability:
                if self._is_executable_tool_record(tool):
                    matches.append(tool)

        if not matches:
            return None

        def score(tool: dict[str, Any]) -> int:
            status = str(tool.get("status", "")).lower()
            value = 0
            if status in {"enabled", "active", "approved", "ready"}:
                value += 100
            if bool((tool.get("verification") or {}).get("sandbox_verification")):
                value += 10
            return value

        return sorted(matches, key=score, reverse=True)[0]

    def _is_executable_tool_record(self, tool: dict[str, Any]) -> bool:
        """Return True only for records that can be passed to the generic runner.

        Blueprint or pending records are useful for audit/review, but they are
        not executable tools. Keeping this filter in the runtime registry avoids
        routing half-generated records into execution and producing errors such
        as unsupported implementation type None.
        """
        status = str(tool.get("status", "")).lower().strip()
        if status in {"missing_implementation_blueprint_generated", "blueprint_generated", "pending", "draft", "disabled"}:
            return False
        implementation = tool.get("implementation")
        if not isinstance(implementation, dict):
            return False
        impl_type = str(implementation.get("type") or "").lower().strip()
        if impl_type not in {"python_function", "python_module", "runtime_python", "runtime_provider"}:
            return False
        if not (implementation.get("module_path") or implementation.get("path")):
            return False
        if not (implementation.get("function") or implementation.get("callable") or "run"):
            return False
        text = json.dumps(tool, ensure_ascii=False, default=str).casefold()
        if "runtime blueprint artifact verified" in text or "requires_runtime_implementation" in text:
            return False
        schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if not props and schema.get("additionalProperties") is True:
            return False
        return True


    def create_missing_tool_spec(
        self,
        *,
        capability: str,
        step: dict[str, Any],
        reason: str = "No runtime tool is configured for this capability.",
        user_input: str = "",
    ) -> dict[str, Any]:
        safe_name = self._safe_name(capability)
        tool_id = f"generated_{safe_name}"

        installed_artifact = self.generated_tool_installer.install_from_step(
            capability=capability,
            step=step,
            user_input=user_input,
        )
        if installed_artifact:
            return {
                **installed_artifact,
                "status": installed_artifact.get("status", "enabled"),
                "generation_status": "runtime_tool_artifact_installed",
                "source_step": step,
            }

        primitive_artifact = self.primitive_tool_factory.build_artifact(
            capability=capability,
            step=step,
            user_input=user_input,
        )
        if primitive_artifact:
            installed_primitive = self.generated_tool_installer.install_artifact(
                artifact=primitive_artifact,
                capability=str(primitive_artifact.get("capability") or capability),
                source_step=step,
                user_input=user_input,
            )
            return {
                **installed_primitive,
                "status": installed_primitive.get("status", "enabled"),
                "generation_status": "runtime_primitive_tool_generated_and_installed",
                "source_step": step,
            }

        blueprint_result = self.blueprint_builder.create_blueprint(
            capability=capability,
            step=step,
            user_input=user_input,
        )

        browser_blueprint = None
        runtime_metadata = blueprint_result.get("blueprint", {}).get("runtime_metadata", {})
        if bool(runtime_metadata.get("requires_browser_blueprint")):
            browser_blueprint = self.browser_blueprint_builder.create_blueprint(
                user_input=user_input,
                step=step,
                capability=capability,
            )

        codegen_request = self.codegen_request_builder.create_request(
            capability=capability,
            blueprint=blueprint_result.get("blueprint", {}),
            user_input=user_input,
        )

        spec = {
            "tool_id": tool_id,
            "name": tool_id,
            "capability": capability,
            "capabilities": [capability],
            "status": "missing_implementation_blueprint_generated",
            "created_at": datetime.utcnow().isoformat(),
            "reason": reason,
            "expected_input": step.get("parameters", {}),
            "source_step": step,
            "blueprint": blueprint_result,
            "browser_blueprint": browser_blueprint,
            "codegen_request": codegen_request,
            "implementation": {
                "type": "runtime_blueprint_pending_generation",
                "notes": (
                    "Runtime generated a tool blueprint and a code generation request. "
                    "A strong model or human developer should generate/approve the implementation."
                ),
            },
            "safety": {
                "requires_human_approval": bool(step.get("requires_human_confirmation", False)),
                "generated_code_must_be_reviewed": True,
            },
        }

        spec_path = self.generated_tools_dir / f"{tool_id}.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

        registry = self.load_registry()
        registry[tool_id] = {
            "tool_id": tool_id,
            "capability": capability,
            "capabilities": [capability],
            "status": "missing_implementation_blueprint_generated",
            "spec_path": str(spec_path),
            "blueprint_dir": blueprint_result.get("tool_dir"),
            "codegen_request_path": codegen_request.get("request_path"),
            "browser_blueprint_dir": browser_blueprint.get("blueprint_dir") if browser_blueprint else None,
        }
        self.save_registry(registry)

        return spec

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in value).strip("_").lower() or "tool"

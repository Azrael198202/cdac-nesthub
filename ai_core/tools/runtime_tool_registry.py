from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_REGISTRY
from ai_core.tools.tool_blueprint_builder import ToolBlueprintBuilder
from ai_core.tools.browser_automation_blueprint import BrowserAutomationBlueprintBuilder
from ai_core.tools.tool_code_generation_request import ToolCodeGenerationRequestBuilder


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
        for tool in registry.values():
            if capability in tool.get("capabilities", []):
                return tool
            if tool.get("capability") == capability:
                return tool
        return None


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

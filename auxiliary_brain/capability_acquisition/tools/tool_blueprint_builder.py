from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_REGISTRY


class ToolBlueprintBuilder:
    """
    Generic runtime tool blueprint builder.

    IMPORTANT:
    This class must not infer business strategy from capability names or
    natural language. The strategy must come from runtime-generated step
    metadata, node config, or LLM-generated blueprint fields.
    """

    def __init__(self) -> None:
        self.tools_dir = RUNTIME_GENERATED / "tools"
        self.registry_path = RUNTIME_REGISTRY / "tool_registry.json"
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        RUNTIME_REGISTRY.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self.registry_path.write_text("{}", encoding="utf-8")

    def create_blueprint(
        self,
        *,
        capability: str,
        step: dict[str, Any],
        user_input: str = "",
        strategy: str | None = None,
    ) -> dict[str, Any]:
        tool_id = f"tool_{self._safe_name(capability)}"
        tool_dir = self.tools_dir / tool_id
        tool_dir.mkdir(parents=True, exist_ok=True)

        runtime_metadata = self._runtime_metadata(step)
        resolved_strategy = strategy or runtime_metadata.get("strategy") or runtime_metadata.get("tool_strategy") or "runtime_defined"

        blueprint = {
            "tool_id": tool_id,
            "capability": capability,
            "status": "blueprint_generated",
            "created_at": datetime.utcnow().isoformat(),
            "source_user_input": user_input,
            "source_step": step,
            "runtime_metadata": runtime_metadata,
            "strategy": resolved_strategy,
            "input_schema": runtime_metadata.get("input_schema", self._default_input_schema()),
            "output_schema": runtime_metadata.get("output_schema", self._default_output_schema()),
            "safety": runtime_metadata.get("safety", self._default_safety(step)),
            "implementation_plan": runtime_metadata.get("implementation_plan", self._default_implementation_plan()),
            "notes": [
                "This blueprint is generic.",
                "Any business-specific strategy must be generated outside ai_core and passed as runtime metadata.",
            ],
        }

        (tool_dir / "tool.json").write_text(json.dumps(blueprint, ensure_ascii=False, indent=2), encoding="utf-8")
        (tool_dir / "README.md").write_text(self._readme(tool_id, blueprint), encoding="utf-8")
        (tool_dir / "test_input.json").write_text(json.dumps(step.get("parameters", {}), ensure_ascii=False, indent=2), encoding="utf-8")
        (tool_dir / "tool.py").write_text(self._placeholder_tool_py(tool_id), encoding="utf-8")

        self._register(tool_id, capability, tool_dir)
        return {"tool_id": tool_id, "tool_dir": str(tool_dir), "blueprint": blueprint}

    def _runtime_metadata(self, step: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(step, dict):
            return {}

        for key in ["tool_blueprint", "tool_metadata", "runtime_metadata", "metadata"]:
            value = step.get(key)
            if isinstance(value, dict):
                return value

        params = step.get("parameters")
        if isinstance(params, dict):
            for key in ["tool_blueprint", "tool_metadata", "runtime_metadata", "metadata"]:
                value = params.get(key)
                if isinstance(value, dict):
                    return value

        return {}

    def _default_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "parameters": {"type": "object"},
                "context": {"type": "object"},
                "human_confirmation": {"type": "boolean"},
            },
            "additionalProperties": True,
        }

    def _default_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "data": {"type": "object"},
                "source": {"type": "string"},
                "requires_human_confirmation": {"type": "boolean"},
            },
            "additionalProperties": True,
        }

    def _default_safety(self, step: dict[str, Any]) -> dict[str, Any]:
        return {
            "can_read_external_data": "runtime_decides",
            "can_write_external_data": False,
            "can_perform_irreversible_action": False,
            "requires_human_confirmation": bool(step.get("requires_human_confirmation", False)),
            "policy_source": "generic_core_default",
        }

    def _default_implementation_plan(self) -> list[str]:
        return [
            "Use runtime-generated blueprint metadata.",
            "Generate implementation outside ai_core.",
            "Generate tests.",
            "Run safety review.",
            "Register tool only after approval.",
        ]

    def _placeholder_tool_py(self, tool_id: str) -> str:
        return (
            f'"""Runtime generated placeholder for {tool_id}."""\n\n'
            "from typing import Any\n\n\n"
            "def run(payload: dict[str, Any]) -> dict[str, Any]:\n"
            "    return {\n"
            '        "status": "not_implemented",\n'
            f'        "tool_id": "{tool_id}",\n'
            '        "message": "Tool blueprint exists, but implementation has not been generated or approved.",\n'
            '        "data": {},\n'
            '        "requires_human_confirmation": True,\n'
            "    }\n"
        )

    def _readme(self, tool_id: str, blueprint: dict[str, Any]) -> str:
        return (
            f"# {tool_id}\n\n"
            "Runtime-generated generic tool blueprint.\n\n"
            "Business-specific strategy is not hardcoded in ai_core.\n"
        )

    def _register(self, tool_id: str, capability: str, tool_dir) -> None:
        try:
            registry = json.loads(self.registry_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            registry = {}
        registry[tool_id] = {
            "tool_id": tool_id,
            "capability": capability,
            "capabilities": [capability],
            "status": "blueprint_generated",
            "tool_dir": str(tool_dir),
            "spec_path": str(tool_dir / "tool.json"),
            "implementation": {
                "type": "runtime_blueprint_pending_generation",
                "function": "run",
                "module_path": str(tool_dir / "tool.py"),
            },
            "executable": False,
        }
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in str(value)).strip("_").lower() or "unknown"

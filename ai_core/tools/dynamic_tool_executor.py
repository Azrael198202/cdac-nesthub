from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from ai_core.runtime.paths import RUNTIME_DIR


class DynamicToolExecutor:
    """Executes runtime generated tools through a stable protocol.

    A tool module must expose: run(input_data: dict, context: dict) -> dict.
    The core does not know domain-specific tool names.
    """

    async def execute_tool(self, tool_name: str, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        tool_path = RUNTIME_DIR / "generated/tools" / f"{tool_name}.py"
        if not tool_path.exists():
            return {
                "ok": False,
                "error": "tool_not_found",
                "message": f"Runtime tool '{tool_name}' does not exist. Generate or configure a real tool before execution.",
            }
        spec = importlib.util.spec_from_file_location(f"runtime_tool_{tool_name}", tool_path)
        if not spec or not spec.loader:
            return {"ok": False, "error": "tool_load_failed"}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "run"):
            return {"ok": False, "error": "invalid_tool_protocol", "message": "Tool must expose run(input_data, context)."}
        result = module.run(input_data, context)
        if not isinstance(result, dict):
            return {"ok": False, "error": "invalid_tool_result", "message": "Tool result must be dict."}
        return result

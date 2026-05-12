from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import Any, Callable

from ai_core.tools.tool_schema_validator import ToolSchemaValidator


class GenericToolRunner:
    """
    Generic runtime tool runner.

    ai_core does not know what a tool does. It only loads a runtime-registered
    implementation, validates input/output against runtime-declared schemas,
    passes generic input data, and returns the tool output.
    """

    def __init__(self) -> None:
        self.schema_validator = ToolSchemaValidator()

    def run_tool(self, tool_spec: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
        implementation = tool_spec.get("implementation", {})
        if not isinstance(implementation, dict):
            return self._error("invalid_tool_spec", "Tool implementation metadata must be an object.")

        if implementation.get("type") not in {"python_function", "python_module", "runtime_python"}:
            return self._error(
                "unsupported_tool_implementation",
                f"Unsupported implementation type: {implementation.get('type')}",
            )

        input_validation = self.schema_validator.validate_input(tool_spec.get("input_schema"), input_data)
        if not input_validation.get("valid"):
            return self._error("tool_input_schema_validation_failed", "; ".join(input_validation.get("errors", [])))

        module_path = implementation.get("module_path") or implementation.get("path")
        function_name = implementation.get("function") or implementation.get("callable") or "run"
        if not module_path:
            return self._error("missing_module_path", "Tool implementation module_path is missing.")

        path = Path(str(module_path))
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            return self._error("module_not_found", f"Tool implementation not found: {path}")

        try:
            fn = self._load_function(path, function_name)
            output = fn(input_data)
            if inspect.isawaitable(output):
                return self._error("async_tool_not_supported_here", "Async tool output must be awaited by an async runner.")
            if not isinstance(output, dict):
                output = {
                    "status": "success",
                    "data": {"value": output},
                    "source": tool_spec.get("tool_id", "runtime_tool"),
                    "requires_human_confirmation": False,
                }
            output_validation = self.schema_validator.validate_output(tool_spec.get("output_schema"), output)
            if not output_validation.get("valid"):
                return self._error("tool_output_schema_validation_failed", "; ".join(output_validation.get("errors", [])))
            return output
        except Exception as exc:
            return self._error("tool_execution_failed", str(exc))

    def _load_function(self, path: Path, function_name: str) -> Callable[[dict[str, Any]], Any]:
        module_name = f"runtime_tool_{path.stem}_{abs(hash(str(path)))}"
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load module spec: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, function_name, None)
        if not callable(fn):
            raise RuntimeError(f"Callable '{function_name}' not found in {path}")
        return fn

    def _error(self, code: str, message: str) -> dict[str, Any]:
        return {
            "status": "error",
            "error": {"code": code, "message": message},
            "data": {},
            "source": "generic_tool_runner",
            "requires_human_confirmation": False,
        }

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import Any, Callable

from ai_core.runtime.provenance import ExecutionProvenanceRecorder
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
        self.provenance = ExecutionProvenanceRecorder()

    def run_tool(self, tool_spec: dict[str, Any], input_data: dict[str, Any], *, run_id: str = "", node_id: str = "", step_id: str = "", capability: str | None = None) -> dict[str, Any]:
        implementation = tool_spec.get("implementation", {})
        if not isinstance(implementation, dict):
            return self._error("invalid_tool_spec", "Tool implementation metadata must be an object.")

        if implementation.get("type") not in {"python_function", "python_module", "runtime_python", "runtime_provider"}:
            return self._error(
                "unsupported_tool_implementation",
                f"Unsupported implementation type: {implementation.get('type')}",
            )

        validation_target = self._runtime_input_for_schema_validation(input_data)
        input_validation = self.schema_validator.validate_input(tool_spec.get("input_schema"), validation_target)
        if not input_validation.get("valid"):
            return self._error("tool_input_schema_validation_failed", "; ".join(input_validation.get("errors", [])))

        if implementation.get("type") == "runtime_provider":
            from ai_core.providers.runtime_provider_invoker import RuntimeProviderInvoker
            from ai_core.providers.runtime_provider_registry import RuntimeProviderRegistry
            provider = implementation.get("provider") if isinstance(implementation.get("provider"), dict) else None
            provider_id = implementation.get("provider_id")
            if provider is None and provider_id:
                provider = RuntimeProviderRegistry().get(str(provider_id))
            if not isinstance(provider, dict):
                return self._error("runtime_provider_not_found", "runtime provider artifact is missing or not registered.")
            output = RuntimeProviderInvoker().invoke(provider, input_data)
            output = self._normalize_tool_output(output, source=str(tool_spec.get("tool_id") or provider.get("provider_id") or "runtime_provider"))
            return output

        module_path = implementation.get("module_path") or implementation.get("path")
        function_name = implementation.get("function") or implementation.get("callable") or "run"
        if not module_path:
            return self._error("missing_module_path", "Tool implementation module_path is missing.")

        path = Path(str(module_path))
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            return self._error("module_not_found", f"Tool implementation not found: {path}")

        trace = self.provenance.start(
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            component_type="runtime_tool",
            component_id=str(tool_spec.get("tool_id") or tool_spec.get("name") or path.stem),
            capability=capability or self._first_capability(tool_spec),
            input_data=self._redact_runtime_sensitive(input_data),
            artifact=tool_spec,
        )

        try:
            fn = self._load_function(path, function_name)
            invocation_payload = self._prepare_invocation_payload(input_data)
            output = fn(invocation_payload)
            if inspect.isawaitable(output):
                result = self._error("async_tool_not_supported_here", "Async tool output must be awaited by an async runner.")
                trace = self.provenance.finish(trace, output=result, status="error", error=result.get("error"))
                return self.provenance.attach(result, trace)
            if not isinstance(output, dict):
                output = {
                    "status": "success",
                    "data": {"value": output},
                    "source": tool_spec.get("tool_id", "runtime_tool"),
                    "requires_human_confirmation": False,
                }
            output = self._normalize_tool_output(output, source=str(tool_spec.get("tool_id") or "runtime_tool"))
            if not self._is_success(output):
                trace = self.provenance.finish(trace, output=output, status="error", error=output.get("error"))
                return self.provenance.attach(output, trace)

            output_schema = tool_spec.get("output_schema")
            output_for_schema = self._output_for_schema_validation(output_schema, output)
            output_validation = self.schema_validator.validate_output(output_schema, output_for_schema)
            if not output_validation.get("valid"):
                data_payload = output.get("data") if isinstance(output.get("data"), dict) else None
                data_validation = self.schema_validator.validate_output(output_schema, data_payload) if data_payload is not None else {"valid": False, "errors": output_validation.get("errors", [])}
                if not data_validation.get("valid"):
                    result = self._error("tool_output_schema_validation_failed", "; ".join(output_validation.get("errors", [])))
                    trace = self.provenance.finish(trace, output=result, status="error", error=result.get("error"))
                    return self.provenance.attach(result, trace)
            trace = self.provenance.finish(
                trace,
                output=output,
                status="success",
                error=None,
            )
            return self.provenance.attach(output, trace)
        except Exception as exc:
            result = self._error("tool_execution_failed", str(exc))
            trace = self.provenance.finish(trace, output=result, status="error", error=result.get("error"))
            return self.provenance.attach(result, trace)

    def _prepare_invocation_payload(self, input_data: Any) -> Any:
        """Return a safe invocation payload for runtime-generated tools.

        The registered-tool runtime envelope may contain generic metadata under
        ``_runtime``. Generated tools are allowed to read optional runtime flags,
        but real executions should not fail just because a verification-only flag
        such as ``dry_run`` is absent. The runner therefore supplies a minimal,
        domain-neutral runtime object for envelope calls while leaving flat legacy
        payloads unchanged.
        """
        if not isinstance(input_data, dict):
            return input_data
        envelope_keys = {"input", "connection", "secrets", "_runtime"}
        if "input" not in input_data and not any(key in input_data for key in envelope_keys - {"input"}):
            return input_data
        payload = dict(input_data)
        runtime = payload.get("_runtime")
        if not isinstance(runtime, dict):
            runtime = {}
        else:
            runtime = dict(runtime)
        runtime.setdefault("dry_run", False)
        payload["_runtime"] = runtime
        return payload


    def _runtime_input_for_schema_validation(self, input_data: Any) -> Any:
        """Return only the runtime input part that should be checked by input_schema.

        Registered runtime tools are invoked with a neutral execution envelope:
        {"input": ..., "connection": ..., "secrets": ..., "_runtime": ...}.
        The tool input schema must validate only the user/runtime input contract,
        while connection_schema and secret_schema are validated by the registered
        tool service before this runner is called.  Older tools may still receive
        a flat payload, so flat dictionaries continue to be validated as-is.
        """
        if not isinstance(input_data, dict):
            return input_data
        envelope_keys = {"input", "connection", "secrets", "_runtime"}
        if "input" in input_data and any(key in input_data for key in envelope_keys - {"input"}):
            nested = input_data.get("input")
            return nested if isinstance(nested, dict) else {"value": nested}
        return input_data

    def _output_for_schema_validation(self, output_schema: Any, output: dict[str, Any]) -> dict[str, Any]:
        """Return the tool-contract output view for output_schema validation.

        The runner may add generic runtime metadata such as ``source`` and
        ``requires_human_confirmation`` for UI/orchestration. Those keys are
        not part of every runtime-generated tool's declared output contract,
        especially when the manifest sets ``additionalProperties: false``.
        Validate only the declared contract fields instead of failing a real
        tool execution because of runner-added envelope metadata.
        """
        if not isinstance(output_schema, dict) or not isinstance(output, dict):
            return output
        properties = output_schema.get("properties")
        if not isinstance(properties, dict):
            return output
        return {key: value for key, value in output.items() if key in properties}

    def _redact_runtime_sensitive(self, value: Any) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key).lower()
                if key_text in {"secrets", "secret", "credential", "credentials"}:
                    if isinstance(item, dict):
                        redacted[key] = {str(k): "***" for k in item.keys()}
                    else:
                        redacted[key] = "***"
                elif key_text == "_runtime" and isinstance(item, dict):
                    nested = dict(item)
                    if isinstance(nested.get("secrets"), dict):
                        nested["secrets"] = {str(k): "***" for k in nested["secrets"].keys()}
                    redacted[key] = self._redact_runtime_sensitive(nested)
                else:
                    redacted[key] = self._redact_runtime_sensitive(item)
            return redacted
        if isinstance(value, list):
            return [self._redact_runtime_sensitive(x) for x in value]
        return value

    def _normalize_tool_output(self, output: dict[str, Any], *, source: str) -> dict[str, Any]:
        raw_status = str(output.get("status", "")).lower().strip()
        has_error = bool(output.get("error"))
        if raw_status in {"error", "failed", "failure"} or has_error:
            error = output.get("error")
            if not isinstance(error, dict):
                error = {"message": str(error or "Runtime tool returned an error.")}
            return {
                "status": "error",
                "error": error,
                "data": output.get("data") if isinstance(output.get("data"), dict) else {},
                "source": output.get("source") or source,
                "requires_human_confirmation": bool(output.get("requires_human_confirmation", False)),
            }
        if raw_status in {"success", "ok", "executed", "completed", "complete"}:
            normalized = dict(output)
            normalized["status"] = "success"
            normalized.setdefault("source", source)
            normalized.setdefault("data", {})
            normalized.setdefault("requires_human_confirmation", False)
            return normalized
        # Plain dict with no explicit status is treated as successful data.
        return {
            "status": "success",
            "data": output.get("data") if isinstance(output.get("data"), dict) else output,
            "source": output.get("source") or source,
            "requires_human_confirmation": bool(output.get("requires_human_confirmation", False)),
        }

    def _is_success(self, output: dict[str, Any]) -> bool:
        return isinstance(output, dict) and str(output.get("status", "")).lower().strip() in {"success", "ok", "executed"} and not output.get("error")

    def _first_capability(self, tool_spec: dict[str, Any]) -> str | None:
        capability = tool_spec.get("capability")
        if isinstance(capability, str) and capability.strip():
            return capability.strip()
        capabilities = tool_spec.get("capabilities")
        if isinstance(capabilities, list) and capabilities:
            return str(capabilities[0])
        return None

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

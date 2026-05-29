from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_REGISTRY, RUNTIME_TRACES
from ai_core.tools.generic_tool_runner import GenericToolRunner


class RuntimeRegisteredToolService:
    """Generic service for listing and executing runtime-registered tools.

    The service does not know what any tool does. It only reads the runtime
    registry, checks that a record is executable, and invokes the declared
    implementation with generic input data.
    """

    def __init__(self, *, registry_path: Path | None = None) -> None:
        self.registry_path = registry_path or (RUNTIME_REGISTRY / "tool_registry.json")
        self.runner = GenericToolRunner()

    def list_tools(self) -> list[dict[str, Any]]:
        registry = self._load_registry()
        tools: list[dict[str, Any]] = []
        for tool_id, spec in registry.items():
            if not isinstance(spec, dict):
                continue
            item = dict(spec)
            item.setdefault("tool_id", str(tool_id))
            item["executable"] = self._is_executable(item)
            tools.append(item)
        tools.sort(key=lambda x: (not bool(x.get("executable")), str(x.get("tool_id") or "")))
        return tools

    def get_tool(self, tool_id: str) -> dict[str, Any] | None:
        registry = self._load_registry()
        spec = registry.get(str(tool_id or ""))
        if not isinstance(spec, dict):
            return None
        out = dict(spec)
        out.setdefault("tool_id", str(tool_id))
        return out

    def execute_tool(self, *, tool_id: str, input_data: Any, run_id: str = "agent_studio_tool_run") -> dict[str, Any]:
        spec = self.get_tool(tool_id)
        if spec is None:
            return {"ok": False, "status": "failed", "error": {"code": "tool_not_found", "message": "Runtime tool is not registered."}}
        if not self._is_executable(spec):
            return {"ok": False, "status": "failed", "error": {"code": "tool_not_executable", "message": "Runtime tool record is not executable."}, "tool": spec}
        payload = input_data if isinstance(input_data, dict) else {"input": input_data}
        result = self.runner.run_tool(spec, payload, run_id=run_id, node_id="agent_studio_registered_tool", step_id=str(tool_id), capability=str(spec.get("capability") or ""))
        out = {
            "ok": str(result.get("status") or "").lower() in {"success", "ok", "executed"},
            "status": result.get("status"),
            "tool_id": tool_id,
            "result": result,
            "tool": self._public_tool_summary(spec),
        }
        self._persist_tool_result(out)
        return out

    def list_tool_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        result_dir = RUNTIME_GENERATED / "results" / "runtime_tool_runs"
        items: list[dict[str, Any]] = []
        if result_dir.exists():
            for path in result_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        data.setdefault("result_path", str(path))
                        items.append(data)
                except Exception:
                    continue
        items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        return items[:limit]

    def list_execution_traces(self, limit: int = 30) -> list[dict[str, Any]]:
        trace_dir = RUNTIME_TRACES / "executions"
        items: list[dict[str, Any]] = []
        if trace_dir.exists():
            for path in trace_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        data.setdefault("trace_path", str(path))
                        items.append(data)
                except Exception:
                    continue
        items.sort(key=lambda x: str(x.get("finished_at") or x.get("started_at") or ""), reverse=True)
        return items[:limit]

    def _persist_tool_result(self, payload: dict[str, Any]) -> None:
        from datetime import datetime, timezone
        result_dir = RUNTIME_GENERATED / "results" / "runtime_tool_runs"
        result_dir.mkdir(parents=True, exist_ok=True)
        created = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        safe_tool = "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in str(payload.get("tool_id") or "runtime_tool"))
        data = dict(payload)
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        path = result_dir / f"{created}_{safe_tool}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {}
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _is_executable(self, spec: dict[str, Any]) -> bool:
        status = str(spec.get("status") or "").lower().strip()
        if status in {"disabled", "pending", "draft", "blueprint_generated", "missing_implementation_blueprint_generated"}:
            return False
        implementation = spec.get("implementation") if isinstance(spec.get("implementation"), dict) else {}
        impl_type = str(implementation.get("type") or "").lower().strip()
        if impl_type not in {"python_function", "python_module", "runtime_python", "runtime_provider"}:
            return False
        if impl_type != "runtime_provider" and not (implementation.get("module_path") or implementation.get("path")):
            return False
        verification = spec.get("verification") if isinstance(spec.get("verification"), dict) else {}
        return bool(verification.get("sandbox_verification")) or status in {"enabled", "active", "approved", "ready"}

    def _public_tool_summary(self, spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool_id": spec.get("tool_id"),
            "name": spec.get("name"),
            "capability": spec.get("capability"),
            "capabilities": spec.get("capabilities") if isinstance(spec.get("capabilities"), list) else [],
            "status": spec.get("status"),
            "verification": spec.get("verification") if isinstance(spec.get("verification"), dict) else {},
        }

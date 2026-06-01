from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_REGISTRY, RUNTIME_TRACES
from ai_core.connections.connection_profile_store import ConnectionProfileStore
from ai_core.tools.generic_tool_runner import GenericToolRunner
from ai_core.runtime.approval_policy_store import RuntimeApprovalPolicyStore


class RuntimeRegisteredToolService:
    """Generic service for listing and executing runtime-registered tools.

    The service does not know what any tool does. It reads runtime-declared
    schemas, checks profile/secret readiness generically, enforces declared
    approval policies, and invokes the registered implementation.
    """

    def __init__(self, *, registry_path: Path | None = None, connection_store: ConnectionProfileStore | None = None, approval_policy_store: RuntimeApprovalPolicyStore | None = None) -> None:
        self.registry_path = registry_path or (RUNTIME_REGISTRY / "tool_registry.json")
        self.runner = GenericToolRunner()
        self.connection_store = connection_store or ConnectionProfileStore()
        self.approval_policy_store = approval_policy_store or RuntimeApprovalPolicyStore()

    def list_tools(self) -> list[dict[str, Any]]:
        registry = self._load_registry()
        tools: list[dict[str, Any]] = []
        for tool_id, spec in registry.items():
            if not isinstance(spec, dict):
                continue
            item = dict(spec)
            item.setdefault("tool_id", str(tool_id))
            item["executable"] = self._is_executable(item)
            item["configuration_status"] = self.connection_store.missing_requirements(tool_spec=item, profile_id="default")
            item["profiles"] = self.connection_store.list_profiles(str(item.get("tool_id") or tool_id))
            item["approval_settings"] = self.approval_policy_store.get_tool_policy(tool_id=str(item.get("tool_id") or tool_id), profile_id="default")
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

    def configure_tool_profile(
        self,
        *,
        tool_id: str,
        profile_id: str = "default",
        config: dict[str, Any] | None = None,
        secrets: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = self.get_tool(tool_id)
        if spec is None:
            return {"ok": False, "status": "failed", "error": {"code": "tool_not_found", "message": "Runtime tool is not registered."}}
        profile = self.connection_store.upsert_profile(
            tool_id=str(spec.get("tool_id") or tool_id),
            profile_id=profile_id or "default",
            config=config if isinstance(config, dict) else {},
            secrets=secrets if isinstance(secrets, dict) else {},
            secret_schema=spec.get("secret_schema") if isinstance(spec.get("secret_schema"), dict) else {},
            metadata={"source": "agent_studio_runtime_profile"},
        )
        return {"ok": True, "status": "configured", "profile": profile, "configuration_status": self.connection_store.missing_requirements(tool_spec=spec, profile_id=profile_id or "default")}

    def execute_tool(
        self,
        *,
        tool_id: str,
        input_data: Any,
        run_id: str = "agent_studio_tool_run",
        profile_id: str = "default",
        approval_confirmed: bool = False,
        remember_approval: bool = False,
    ) -> dict[str, Any]:
        spec = self.get_tool(tool_id)
        if spec is None:
            return {"ok": False, "status": "failed", "error": {"code": "tool_not_found", "message": "Runtime tool is not registered."}}
        if not self._is_executable(spec):
            return {"ok": False, "status": "failed", "error": {"code": "tool_not_executable", "message": "Runtime tool record is not executable."}, "tool": spec}
        profile_id = profile_id or "default"
        missing = self.connection_store.missing_requirements(tool_spec=spec, profile_id=profile_id)
        if not missing.get("configured"):
            return {
                "ok": False,
                "status": "requires_configuration",
                "error": {"code": "runtime_configuration_required", "message": "Runtime-declared configuration or secret values are missing."},
                "configuration_status": missing,
                "tool": self._public_tool_summary(spec),
            }
        approval = spec.get("approval_policy") if isinstance(spec.get("approval_policy"), dict) else {}
        approval_settings = self.approval_policy_store.get_tool_policy(tool_id=str(spec.get("tool_id") or tool_id), profile_id=profile_id)
        if bool(approval.get("required")) and not approval_confirmed and self.approval_policy_store.is_auto_approved(tool_id=str(spec.get("tool_id") or tool_id), profile_id=profile_id):
            approval_confirmed = True
        if bool(approval.get("required")) and not approval_confirmed:
            return {
                "ok": False,
                "status": "requires_human_confirmation",
                "error": {"code": "human_confirmation_required", "message": "This runtime-generated capability requires confirmation before execution."},
                "approval_policy": approval,
                "approval_settings": approval_settings,
                "preview": self._approval_preview(input_data),
                "tool": self._public_tool_summary(spec),
            }
        if approval_confirmed:
            self.approval_policy_store.record_confirmation(tool_id=str(spec.get("tool_id") or tool_id), profile_id=profile_id, remember=remember_approval)
        payload = input_data if isinstance(input_data, dict) else {"input": input_data}
        payload = self._apply_runtime_invocation_defaults(spec=spec, payload=payload, approval_confirmed=approval_confirmed)
        runtime_context = self.connection_store.runtime_context_for(tool_spec=spec, profile_id=profile_id)
        if runtime_context.get("connection") or runtime_context.get("secrets") or runtime_context.get("secret_refs"):
            payload = dict(payload)
            payload["_runtime"] = runtime_context
        result = self.runner.run_tool(spec, payload, run_id=run_id, node_id="agent_studio_registered_tool", step_id=str(tool_id), capability=str(spec.get("capability") or ""))
        out = {
            "ok": str(result.get("status") or "").lower() in {"success", "ok", "executed"},
            "status": result.get("status"),
            "tool_id": tool_id,
            "profile_id": profile_id,
            "result": result,
            "tool": self._public_tool_summary(spec),
            "approval_settings": self.approval_policy_store.get_tool_policy(tool_id=str(spec.get("tool_id") or tool_id), profile_id=profile_id),
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

    def list_profiles(self, tool_id: str | None = None) -> list[dict[str, Any]]:
        return self.connection_store.list_profiles(tool_id)


    def _apply_runtime_invocation_defaults(self, *, spec: dict[str, Any], payload: Any, approval_confirmed: bool) -> dict[str, Any]:
        """Apply registry-declared invocation defaults before execution.

        Runtime acquisition may use mock or dry-run values during sandbox
        verification, while the enabled runtime capability may need a different
        user-execution default.  The core stays capability-agnostic: it only
        reads defaults declared on the registered tool record and applies them
        to missing input fields.
        """
        data = dict(payload) if isinstance(payload, dict) else {"input": payload}
        policy = spec.get("runtime_execution_policy") if isinstance(spec.get("runtime_execution_policy"), dict) else {}
        defaults: dict[str, Any] = {}
        generic_defaults = policy.get("default_input_values")
        if isinstance(generic_defaults, dict):
            defaults.update(generic_defaults)
        if approval_confirmed:
            confirmed_defaults = policy.get("confirmed_input_values")
            if isinstance(confirmed_defaults, dict):
                defaults.update(confirmed_defaults)
            user_defaults = policy.get("user_execution_input_values")
            if isinstance(user_defaults, dict):
                defaults.update(user_defaults)
        for key, value in defaults.items():
            if key == "_runtime":
                continue
            if key not in data or data.get(key) in (None, "", [], {}):
                data[key] = value
        return data

    def _approval_preview(self, input_data: Any) -> dict[str, Any]:
        if isinstance(input_data, dict):
            preview = {k: ("***" if str(k).lower() in {"secret", "secrets", "credential", "credentials"} else v) for k, v in input_data.items() if k != "_runtime"}
            return {"input": preview}
        return {"input": input_data}

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
            "input_schema": spec.get("input_schema") if isinstance(spec.get("input_schema"), dict) else {},
            "output_schema": spec.get("output_schema") if isinstance(spec.get("output_schema"), dict) else {},
            "connection_schema": spec.get("connection_schema") if isinstance(spec.get("connection_schema"), dict) else {},
            "secret_schema": spec.get("secret_schema") if isinstance(spec.get("secret_schema"), dict) else {},
            "approval_policy": spec.get("approval_policy") if isinstance(spec.get("approval_policy"), dict) else {},
            "approval_settings": self.approval_policy_store.get_tool_policy(tool_id=str(spec.get("tool_id") or spec.get("name") or ""), profile_id="default"),
            "verification": spec.get("verification") if isinstance(spec.get("verification"), dict) else {},
        }

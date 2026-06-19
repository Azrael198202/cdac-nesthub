from __future__ import annotations

import json
import shutil
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_REGISTRY, RUNTIME_TRACES
from ai_core.connections.connection_profile_store import ConnectionProfileStore
from auxiliary_brain.runtime_tools.generic_tool_runner import GenericToolRunner
from ai_core.runtime.approval_policy_store import RuntimeApprovalPolicyStore
from auxiliary_brain.runtime.self_repair.repair_orchestrator import FeedbackRepairOrchestrator

_NO_DEFAULT = object()


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
        self.repair_orchestrator = FeedbackRepairOrchestrator()

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
            item["approval_settings"] = self._effective_approval_settings_for_public_tool(item, profile_id="default")
            tools.append(item)
        tools.sort(key=lambda x: (not bool(x.get("executable")), str(x.get("tool_id") or "")))
        return tools

    def effective_approval_settings(self, *, spec: dict[str, Any], profile_id: str = "default") -> dict[str, Any]:
        """Return the exact approval decision used by execution.

        This is the single authority for the approval UI and the executor.
        It intentionally remains capability-agnostic: explicit Runtime Studio
        policy wins; otherwise the imported manifest policy is used.
        """
        tool_id = str(spec.get("tool_id") or spec.get("name") or "tool")
        stored = self.approval_policy_store.get_tool_policy(tool_id=tool_id, profile_id=profile_id or "default")
        approval = spec.get("approval_policy") if isinstance(spec.get("approval_policy"), dict) else {}
        mode = self._effective_approval_mode(spec=spec, approval=approval, approval_settings=stored)
        requires_confirmation = self._approval_required(spec, approval, stored)
        out = dict(stored) if isinstance(stored, dict) else {}
        out.update({
            "tool_id": tool_id,
            "profile_id": profile_id or "default",
            "mode": mode,
            "effective_mode": mode,
            "source": "runtime_studio_policy" if bool(out.get("explicit")) else "tool_manifest",
            "requires_confirmation": requires_confirmation,
            "trusted": bool(out.get("trusted")),
            "explicit": bool(out.get("explicit")),
        })
        return out

    def _effective_approval_settings_for_public_tool(self, spec: dict[str, Any], profile_id: str = "default") -> dict[str, Any]:
        return self.effective_approval_settings(spec=spec, profile_id=profile_id)

    def get_tool(self, tool_id: str) -> dict[str, Any] | None:
        registry = self._load_registry()
        spec = registry.get(str(tool_id or ""))
        if not isinstance(spec, dict):
            return None
        out = dict(spec)
        out.setdefault("tool_id", str(tool_id))
        return out

    def _effective_approval_mode(self, *, spec: dict[str, Any], approval: dict[str, Any], approval_settings: dict[str, Any]) -> str:
        """Resolve the active approval mode without capability-specific rules.

        The runtime approval policy is the current operator control plane and
        must take precedence over import-time manifest defaults.  The policy
        store returns a capability-agnostic default when no explicit row exists;
        honoring that value keeps the confirmation stage consistent with the
        Runtime Studio setting instead of silently executing because an imported
        artifact manifest said ``never``.
        """
        valid = {"always", "once", "never"}
        # A stored Runtime Studio policy overrides the artifact only when the
        # policy row is explicit.  The policy store's default must not turn a
        # manifest-level ``never`` into an ``always`` approval gate; otherwise
        # no-parameter read-only tasks pause once and only run on a second
        # resume command.
        if isinstance(approval_settings, dict) and bool(approval_settings.get("explicit")):
            mode = str(approval_settings.get("mode") or "always").strip().lower()
            return mode if mode in valid else "always"
        mode = str(approval.get("mode") or approval.get("default_mode") or "").strip().lower()
        if mode in valid:
            return mode
        return "always" if bool(approval.get("required")) else "never"

    def _approval_required(self, spec: dict[str, Any], approval: dict[str, Any], approval_settings: dict[str, Any] | None = None) -> bool:
        approval_settings = approval_settings if isinstance(approval_settings, dict) else {}
        mode = self._effective_approval_mode(spec=spec, approval=approval, approval_settings=approval_settings)
        if mode == "never":
            return False
        if mode == "once" and bool(approval_settings.get("trusted")):
            return False
        if mode in {"always", "once"}:
            return True
        if not bool(approval.get("required")):
            return False
        runtime_policy = spec.get("runtime_execution_policy") if isinstance(spec.get("runtime_execution_policy"), dict) else {}
        side_effects = str(runtime_policy.get("side_effects") or "").strip().casefold()
        safe_effects = {"none", "pure", "read_only", "read-only"}
        if side_effects in safe_effects:
            return False
        ambiguous = {"", "runtime_declared", "unknown", "unspecified"}
        if side_effects in ambiguous:
            connection_schema = spec.get("connection_schema") if isinstance(spec.get("connection_schema"), dict) else {}
            secret_schema = spec.get("secret_schema") if isinstance(spec.get("secret_schema"), dict) else {}
            has_connection_contract = bool(connection_schema.get("required") or connection_schema.get("properties"))
            has_secret_contract = bool(secret_schema.get("required") or secret_schema.get("properties"))
            if not has_connection_contract and not has_secret_contract:
                return False
        return True

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
        normalized_config = self._coerce_by_schema(
            config if isinstance(config, dict) else {},
            spec.get("connection_schema") if isinstance(spec.get("connection_schema"), dict) else {},
        )
        profile = self.connection_store.upsert_profile(
            tool_id=str(spec.get("tool_id") or tool_id),
            profile_id=profile_id or "default",
            config=normalized_config,
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
        input_schema = spec.get("input_schema") if isinstance(spec.get("input_schema"), dict) else {}
        connection_schema = spec.get("connection_schema") if isinstance(spec.get("connection_schema"), dict) else {}
        secret_schema = spec.get("secret_schema") if isinstance(spec.get("secret_schema"), dict) else {}

        raw_runtime_input = input_data if isinstance(input_data, dict) else {"value": input_data}
        runtime_input, execution_controls = self._split_execution_controls_from_payload(raw_runtime_input, input_schema=input_schema)
        if not approval_confirmed and self._truthy_execution_control(execution_controls, "approval_confirmed"):
            approval_confirmed = True
        if not remember_approval and self._truthy_execution_control(execution_controls, "remember_approval"):
            remember_approval = True

        approval = spec.get("approval_policy") if isinstance(spec.get("approval_policy"), dict) else {}
        approval_settings = self.effective_approval_settings(spec=spec, profile_id=profile_id)
        approval_required = bool(approval_settings.get("requires_confirmation"))
        if approval_required and not approval_confirmed and self.approval_policy_store.is_auto_approved(tool_id=str(spec.get("tool_id") or tool_id), profile_id=profile_id):
            approval_confirmed = True
        if approval_required and not approval_confirmed:
            return {
                "ok": False,
                "status": "requires_human_confirmation",
                "error": {"code": "human_confirmation_required", "message": "This runtime-generated capability requires confirmation before execution."},
                "approval_policy": approval,
                "approval_settings": approval_settings,
                "effective_approval_policy": approval_settings,
                "preview": self._approval_preview(runtime_input),
                "tool": self._public_tool_summary(spec),
            }
        if approval_confirmed:
            self.approval_policy_store.record_confirmation(tool_id=str(spec.get("tool_id") or tool_id), profile_id=profile_id, remember=remember_approval)

        runtime_input = self._coerce_by_schema(runtime_input, input_schema)
        runtime_input = self._drop_empty_optional_fields(payload=runtime_input, schema=input_schema)
        runtime_input = self._apply_runtime_invocation_defaults(spec=spec, payload=runtime_input, approval_confirmed=approval_confirmed)
        runtime_input, _ = self._split_execution_controls_from_payload(runtime_input, input_schema=input_schema)
        runtime_input = self._drop_empty_optional_fields(payload=runtime_input, schema=input_schema)
        runtime_input = self._apply_schema_invocation_defaults(payload=runtime_input, schema=input_schema)
        runtime_input, _ = self._split_execution_controls_from_payload(runtime_input, input_schema=input_schema)
        runtime_input = self._coerce_by_schema(runtime_input, input_schema)
        runtime_input = self._drop_empty_optional_fields(payload=runtime_input, schema=input_schema)
        runtime_input = self._project_payload_to_schema(runtime_input, input_schema)

        input_validation = self.runner.schema_validator.validate_input(input_schema, runtime_input)
        if not input_validation.get("valid"):
            return self._validation_error(
                code="tool_input_schema_validation_failed",
                message="Runtime input values do not match the registered input schema.",
                errors=input_validation.get("errors", []),
                tool_id=tool_id,
                profile_id=profile_id,
                schema_section="input_schema",
            )

        runtime_context = self.connection_store.runtime_context_for(tool_spec=spec, profile_id=profile_id)
        connection_values = self._coerce_by_schema(
            runtime_context.get("connection") if isinstance(runtime_context.get("connection"), dict) else {},
            connection_schema,
        )
        secret_values = self._coerce_by_schema(
            runtime_context.get("secrets") if isinstance(runtime_context.get("secrets"), dict) else {},
            secret_schema,
        )

        connection_validation = self.runner.schema_validator.validate_input(connection_schema, connection_values)
        if not connection_validation.get("valid"):
            return self._validation_error(
                code="tool_connection_schema_validation_failed",
                message="Profile connection values do not match the registered connection schema.",
                errors=connection_validation.get("errors", []),
                tool_id=tool_id,
                profile_id=profile_id,
                schema_section="connection_schema",
            )

        secret_validation = self.runner.schema_validator.validate_input(secret_schema, secret_values)
        if not secret_validation.get("valid"):
            return self._validation_error(
                code="tool_secret_schema_validation_failed",
                message="Profile secret values do not match the registered secret schema.",
                errors=secret_validation.get("errors", []),
                tool_id=tool_id,
                profile_id=profile_id,
                schema_section="secret_schema",
            )

        runtime_flags = {
            "profile_id": profile_id,
            "connection": connection_values,
            "secrets": secret_values,
            "secret_refs": runtime_context.get("secret_refs") if isinstance(runtime_context.get("secret_refs"), dict) else {},
            "approval_confirmed": bool(approval_confirmed),
        }
        if "dry_run" in execution_controls:
            runtime_flags["dry_run"] = self._truthy_execution_control(execution_controls, "dry_run")
        invocation_payload = {
            "input": runtime_input,
            "connection": connection_values,
            "secrets": secret_values,
            "_runtime": runtime_flags,
        }
        result = self.runner.run_tool(spec, invocation_payload, run_id=run_id, node_id="agent_studio_registered_tool", step_id=str(tool_id), capability=str(spec.get("capability") or ""))
        result = self._repair_structural_placeholder_echo(result=result, runtime_input=runtime_input)
        success = str(result.get("status") or "").lower() in {"success", "ok", "executed", "completed"}
        out = {
            "ok": success,
            "status": result.get("status"),
            "tool_id": tool_id,
            "profile_id": profile_id,
            "result": result,
            "tool": self._public_tool_summary(spec),
            "approval_settings": self.effective_approval_settings(spec=spec, profile_id=profile_id),
        }
        if not success:
            try:
                repair = self.repair_orchestrator.propose_for_tool_result(
                    run_id=run_id,
                    tool_id=tool_id,
                    profile_id=profile_id,
                    result=result,
                    tool_spec=spec,
                    input_payload=runtime_input,
                    expected_contract={"input_schema": input_schema, "connection_schema": connection_schema, "secret_schema": secret_schema},
                    runtime_state={"profile_id": profile_id, "tool_id": tool_id},
                )
                out["repair"] = repair
                out["human_readable_error"] = repair.get("user_message")
            except Exception as exc:
                out["repair"] = {"status": "repair_proposal_failed", "error": str(exc)}
        self._persist_tool_result(out)
        return out


    def _repair_structural_placeholder_echo(self, *, result: dict[str, Any], runtime_input: dict[str, Any]) -> dict[str, Any]:
        """Repair structurally invalid placeholder echoes in successful output.

        A generated runtime tool may accidentally echo a format token such as
        ``YYYY-MM-DD HH:mm`` instead of rendering a live value.  This repair is
        generic and guarded: it only changes successful outputs when an output
        string exactly equals the submitted ``format`` input and that format
        contains common date/time tokens.  It does not depend on a tool id or a
        scenario name.
        """
        if not isinstance(result, dict) or str(result.get("status") or "").lower() not in {"success", "ok", "executed", "completed"}:
            return result
        if not isinstance(runtime_input, dict):
            return result
        fmt = str(runtime_input.get("format") or "").strip()
        if not fmt or not self._looks_like_datetime_token_format(fmt):
            return result
        rendered = self._render_datetime_token_format(fmt, runtime_input.get("timezone"))
        if not rendered or rendered == fmt:
            return result
        changed = False

        def repair_value(value: Any) -> Any:
            nonlocal changed
            if isinstance(value, str) and value.strip() == fmt:
                changed = True
                return rendered
            if isinstance(value, dict):
                return {k: repair_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [repair_value(v) for v in value]
            return value

        repaired = dict(result)
        for key in ("data", "output", "result"):
            if key in repaired:
                repaired[key] = repair_value(repaired[key])
        if changed:
            repaired.setdefault("runtime_repairs", []).append({
                "kind": "structural_placeholder_echo_repair",
                "field_source": "format",
                "format": fmt,
            })
        return repaired

    def _looks_like_datetime_token_format(self, fmt: str) -> bool:
        text = str(fmt or "")
        return bool(re.search(r"\bY{2,4}\b|\bM{2}\b|\bD{2}\b|\bH{2}\b|\bh{2}\b|\bm{2}\b|\bs{2}\b", text))

    def _render_datetime_token_format(self, fmt: str, timezone_name: Any = None) -> str:
        tz = timezone.utc
        tz_text = str(timezone_name or "").strip()
        if tz_text and ZoneInfo is not None:
            try:
                tz = ZoneInfo(tz_text)
            except Exception:
                tz = timezone.utc
        now = datetime.now(tz)
        replacements = [
            ("YYYY", f"{now.year:04d}"),
            ("yyyy", f"{now.year:04d}"),
            ("YY", f"{now.year % 100:02d}"),
            ("MM", f"{now.month:02d}"),
            ("DD", f"{now.day:02d}"),
            ("dd", f"{now.day:02d}"),
            ("HH", f"{now.hour:02d}"),
            ("hh", f"{now.hour:02d}"),
            ("mm", f"{now.minute:02d}"),
            ("ss", f"{now.second:02d}"),
        ]
        out = str(fmt)
        for token, value in replacements:
            out = out.replace(token, value)
        return out


    def _validation_error(self, *, code: str, message: str, errors: Any, tool_id: str, profile_id: str, schema_section: str) -> dict[str, Any]:
        normalized_errors = errors if isinstance(errors, list) else [str(errors)]
        payload = {
            "ok": False,
            "status": "failed",
            "tool_id": tool_id,
            "profile_id": profile_id,
            "error": {
                "code": code,
                "message": message,
                "schema_section": schema_section,
                "errors": normalized_errors,
            },
        }
        try:
            repair = self.repair_orchestrator.propose_for_tool_result(
                run_id=f"validation_{tool_id}",
                tool_id=tool_id,
                profile_id=profile_id,
                result=payload,
                tool_spec=self.get_tool(tool_id) or {},
                input_payload={},
                expected_contract={schema_section: {}},
                runtime_state={"schema_section": schema_section, "errors": normalized_errors},
            )
            payload["repair"] = repair
            payload["human_readable_error"] = repair.get("user_message")
        except Exception:
            pass
        self._persist_tool_result(payload)
        return payload


    def delete_tool(self, tool_id: str, *, delete_artifacts: bool = False, delete_profiles: bool = False) -> dict[str, Any]:
        tool_id = str(tool_id or "").strip()
        if not tool_id:
            return {"ok": False, "status": "failed", "error": {"code": "missing_tool_id", "message": "A runtime capability id is required."}}
        registry = self._load_registry()
        if tool_id not in registry:
            return {"ok": False, "status": "not_found", "tool_id": tool_id}
        spec = registry.pop(tool_id)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        removed: dict[str, Any] = {"registry": True}
        if delete_profiles:
            profile_dir = Path("runtime") / "connections" / tool_id
            if profile_dir.exists():
                shutil.rmtree(profile_dir, ignore_errors=True)
                removed["profiles"] = str(profile_dir)
        if delete_artifacts:
            paths = []
            for key in ("module_path", "spec_path"):
                value = spec.get(key) if isinstance(spec, dict) else None
                if value:
                    paths.append(Path(str(value)))
            artifact_dir = Path("runtime") / "generated" / "tools" / tool_id
            paths.append(artifact_dir)
            for path in paths:
                try:
                    if path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)
                    elif path.is_file():
                        path.unlink()
                except Exception:
                    pass
            removed["artifacts"] = True
        return {"ok": True, "status": "deleted", "tool_id": tool_id, "removed": removed}

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



    def _coerce_by_schema(self, value: Any, schema: dict[str, Any] | None) -> Any:
        """Coerce browser/runtime string values to schema-declared JSON types.

        This stays capability-agnostic: it only follows runtime-declared JSON
        schema types. It prevents common UI issues such as the string "false"
        being treated as truthy by generated Python code.
        """
        if not isinstance(schema, dict):
            return value
        expected = schema.get("type")
        if isinstance(expected, list):
            expected = next((x for x in expected if x != "null"), expected[0] if expected else None)
        if expected == "boolean":
            return self._parse_bool(value)
        if expected == "integer":
            try:
                if value in (None, ""):
                    return value
                return int(value)
            except Exception:
                return value
        if expected == "number":
            try:
                if value in (None, ""):
                    return value
                return float(value)
            except Exception:
                return value
        if expected == "array" and isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else value
            except Exception:
                return value
        if expected == "object" and isinstance(value, dict):
            props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            return {k: self._coerce_by_schema(v, props.get(k) if isinstance(props.get(k), dict) else {}) for k, v in value.items()}
        if expected == "object" and isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return self._coerce_by_schema(parsed, schema)
            except Exception:
                return value
        if isinstance(value, dict):
            props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            return {k: self._coerce_by_schema(v, props.get(k) if isinstance(props.get(k), dict) else {}) for k, v in value.items()}
        return value

    def _parse_bool(self, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if value is None or value == "":
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().casefold()
        if text in {"true", "1", "yes", "y", "on"}:
            return True
        if text in {"false", "0", "no", "n", "off"}:
            return False
        return value


    _EXECUTION_CONTROL_NAMES = {
        "approval_confirmed",
        "remember_approval",
        "confirm",
        "confirmed",
        "approval",
        "approved",
        "dry_run",
    }

    def _control_tail(self, key: Any) -> str:
        return str(key or "").strip().rsplit(".", 1)[-1].replace("-", "_").casefold()

    def _schema_property_names(self, schema: dict[str, Any] | None) -> set[str]:
        props = schema.get("properties") if isinstance(schema, dict) and isinstance(schema.get("properties"), dict) else {}
        names: set[str] = set()
        for name in props.keys():
            text = str(name or "").strip()
            if text:
                names.add(text)
                names.add(text.replace("-", "_").casefold())
        return names

    def _schema_declares_property(self, key: Any, schema: dict[str, Any] | None) -> bool:
        tail = self._control_tail(key)
        return str(key or "") in self._schema_property_names(schema) or tail in self._schema_property_names(schema)

    def _split_execution_controls_from_payload(self, payload: Any, *, input_schema: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        """Separate execution controls from capability business input.

        This is schema-driven and capability-agnostic. Approval controls may be
        submitted by UI/preflight/resume flows, but they are consumed by the
        executor approval layer. They are kept out of the tool payload unless the
        tool's own declared input schema explicitly contains that field.
        """
        data = dict(payload) if isinstance(payload, dict) else {"value": payload}
        tool_input: dict[str, Any] = {}
        controls: dict[str, Any] = {}
        for key, value in data.items():
            tail = self._control_tail(key)
            if tail in self._EXECUTION_CONTROL_NAMES and not self._schema_declares_property(key, input_schema):
                controls[tail] = value
            else:
                tool_input[key] = value
        return tool_input, controls

    def _truthy_execution_control(self, controls: dict[str, Any], name: str) -> bool:
        value = controls.get(name)
        if value is None:
            return False
        parsed = self._parse_bool(value)
        return bool(parsed)

    def _project_payload_to_schema(self, payload: Any, schema: dict[str, Any] | None) -> dict[str, Any]:
        """Project payload to the declared object schema when strict.

        Generated capabilities are invoked through their registry contract. If a
        schema declares object properties and does not allow additional
        properties, only declared fields are passed to the tool implementation.
        """
        data = dict(payload) if isinstance(payload, dict) else {"value": payload}
        if not isinstance(schema, dict) or schema.get("type") != "object":
            return data
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if schema.get("additionalProperties") is False:
            return {k: v for k, v in data.items() if k in props}
        return data

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


    def _apply_schema_invocation_defaults(self, *, payload: Any, schema: dict[str, Any] | None) -> dict[str, Any]:
        """Apply schema-declared defaults without inventing optional values.

        The runtime must not turn an omitted optional field into an empty string,
        empty object, or empty array just because the JSON Schema declares a
        type.  For wrapped Python callables, an omitted optional argument often
        means "use the function default" while an empty value can mean "execute
        a no-op".  Therefore this method is contract-driven:

        * explicit ``default`` values in schema are materialized;
        * required fields may receive neutral runtime values when absent;
        * optional fields without explicit defaults are left absent.
        """
        data = dict(payload) if isinstance(payload, dict) else {"value": payload}
        if not isinstance(schema, dict):
            return data
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = {str(x) for x in schema.get("required", []) if isinstance(x, str)}
        for key, spec in props.items():
            if key in data and data.get(key) is not None:
                continue
            if not isinstance(spec, dict):
                continue
            if "default" in spec:
                data[key] = spec.get("default")
                continue
            if key not in required:
                continue
            expected = spec.get("type")
            if isinstance(expected, list):
                expected = next((x for x in expected if x != "null"), expected[0] if expected else None)
            neutral = self._neutral_value_for_json_type(expected)
            if neutral is not _NO_DEFAULT:
                data[key] = neutral
        return data

    def _drop_empty_optional_fields(self, *, payload: Any, schema: dict[str, Any] | None) -> dict[str, Any]:
        """Remove empty submitted values for optional schema fields.

        UI forms often submit optional fields as ``""`` or ``[]``. Passing those
        values to a generated wrapper is not equivalent to omitting the field:
        the wrapped function's own default value is bypassed.  This method keeps
        required fields intact so validation can still catch missing required
        input, and drops only optional fields that are effectively blank.
        """
        data = dict(payload) if isinstance(payload, dict) else {"value": payload}
        if not isinstance(schema, dict):
            return data
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = {str(x) for x in schema.get("required", []) if isinstance(x, str)}
        out: dict[str, Any] = {}
        for key, value in data.items():
            if key in props and key not in required and self._is_blank_optional_value(value):
                continue
            out[key] = value
        return out

    def _is_blank_optional_value(self, value: Any) -> bool:
        if value is None:
            return True
        if value == "":
            return True
        if isinstance(value, (list, tuple, set, dict)) and len(value) == 0:
            return True
        return False

    def _neutral_value_for_json_type(self, expected: Any) -> Any:
        return {
            "string": "",
            "array": [],
            "object": {},
            "boolean": False,
        }.get(str(expected), _NO_DEFAULT)

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
            "approval_settings": self.effective_approval_settings(spec=spec, profile_id="default"),
            "verification": spec.get("verification") if isinstance(spec.get("verification"), dict) else {},
        }

from __future__ import annotations

import copy
import re
from typing import Any


class RegisteredToolParameterBridge:
    """Bridge participant/task parameter values into a registered-tool payload.

    The bridge is intentionally schema-driven and capability-agnostic.  Agent
    and task runtimes may collect values using participant-scoped field names,
    display-name scoped field names, or plain parameter names.  A registered
    tool, however, must receive one clean payload that matches its input schema.
    This class performs that stable conversion without deciding what the tool
    does.
    """

    def build_invocation(
        self,
        *,
        participant: dict[str, Any],
        tool_spec: dict[str, Any] | None = None,
        provided_values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        schema = self._input_schema(participant=participant, tool_spec=tool_spec)
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = {str(x) for x in schema.get("required", []) if str(x).strip()} if isinstance(schema.get("required"), list) else set()
        value_sources = self._merged_value_sources(participant=participant, provided_values=provided_values)
        payload: dict[str, Any] = {}
        for name, prop in properties.items():
            field_name = str(name)
            raw = self._lookup_field_value(field_name, participant=participant, values=value_sources)
            if self._is_empty(raw):
                continue
            normalized = self._normalize_for_schema(raw, prop if isinstance(prop, dict) else {})
            if not self._is_empty(normalized):
                payload[field_name] = normalized
        missing = [name for name in required if self._is_empty(payload.get(name))]
        return {
            "ok": not missing,
            "input_data": payload,
            "missing": missing,
            "schema_required": sorted(required),
            "accepted_input_keys": sorted(payload.keys()),
        }

    def input_fields_from_schema(self, *, participant: dict[str, Any], tool_spec: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return UI-ready fields from a registered tool input schema."""
        schema = self._input_schema(participant=participant, tool_spec=tool_spec)
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = {str(x) for x in schema.get("required", []) if str(x).strip()} if isinstance(schema.get("required"), list) else set()
        pid = self._participant_id(participant)
        pname = self._participant_name(participant)
        fields: list[dict[str, Any]] = []
        for name, prop in properties.items():
            prop = prop if isinstance(prop, dict) else {}
            field_name = str(name)
            schema_type = str(prop.get("type") or "string")
            fields.append({
                "kind": "agent_parameter_required",
                "field": f"{pid}.{field_name}" if pid else field_name,
                "name": f"{pid}.{field_name}" if pid else field_name,
                "parameter_name": field_name,
                "participant_id": pid,
                "participant_name": pname,
                "label": f"{pname} / {prop.get('title') or field_name}" if pname else str(prop.get("title") or field_name),
                "message": str(prop.get("description") or f"Please provide {field_name}."),
                "input_type": "list" if schema_type == "array" else schema_type,
                "required": field_name in required,
                "collection_mode": "repeat_until_done" if schema_type == "array" else "single_value",
                "runtime_required": field_name in required,
                "blocking": field_name in required,
                "execution_required": field_name in required,
                "source_schema_type": schema_type,
            })
        return fields

    def _input_schema(self, *, participant: dict[str, Any], tool_spec: dict[str, Any] | None) -> dict[str, Any]:
        if isinstance(tool_spec, dict) and isinstance(tool_spec.get("input_schema"), dict):
            return copy.deepcopy(tool_spec.get("input_schema") or {})
        profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
        summary = profile.get("tool_summary") if isinstance(profile.get("tool_summary"), dict) else {}
        schema = summary.get("input_schema") if isinstance(summary.get("input_schema"), dict) else {}
        return copy.deepcopy(schema)

    def _merged_value_sources(self, *, participant: dict[str, Any], provided_values: dict[str, Any] | None) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        runtime_parameters = participant.get("runtime_parameters") if isinstance(participant.get("runtime_parameters"), dict) else {}
        merged.update(runtime_parameters)
        contract = participant.get("parameter_contract") if isinstance(participant.get("parameter_contract"), dict) else {}
        params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
        for param in params:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "").strip()
            if name and name not in merged and not self._is_empty(param.get("values")):
                merged[name] = param.get("values")
        if isinstance(provided_values, dict):
            merged.update(provided_values)
        return merged

    def _lookup_field_value(self, field_name: str, *, participant: dict[str, Any], values: dict[str, Any]) -> Any:
        aliases = [field_name]
        pid = self._participant_id(participant)
        pname = self._participant_name(participant)
        safe_pname = self._safe_key(pname)
        for prefix in (pid, pname, safe_pname):
            if prefix:
                aliases.extend([f"{prefix}.{field_name}", f"{prefix}_{field_name}"])
        # Prefer scoped values over plain names when both exist in submitted UI data.
        ordered_aliases = [a for a in aliases if a != field_name] + [field_name]
        lowered = {str(k).casefold(): k for k in values.keys()}
        for alias in ordered_aliases:
            if alias in values:
                return values[alias]
            key = lowered.get(alias.casefold())
            if key is not None:
                return values[key]
        return None

    def _normalize_for_schema(self, raw: Any, prop: dict[str, Any]) -> Any:
        schema_type = str(prop.get("type") or "string").strip().lower()
        if schema_type == "array":
            items = self._as_list(raw)
            item_schema = prop.get("items") if isinstance(prop.get("items"), dict) else {}
            return [self._normalize_scalar_or_object(v, item_schema) for v in items if not self._is_empty(v)]
        if schema_type == "object":
            if isinstance(raw, dict):
                return raw
            return {"value": raw} if not self._is_empty(raw) else {}
        return self._normalize_scalar_or_object(raw, prop)

    def _normalize_scalar_or_object(self, raw: Any, prop: dict[str, Any]) -> Any:
        schema_type = str(prop.get("type") or "string").strip().lower()
        if isinstance(raw, list):
            raw = next((x for x in raw if not self._is_empty(x)), None)
        if schema_type in {"integer", "number"}:
            try:
                return int(raw) if schema_type == "integer" else float(raw)
            except Exception:
                return raw
        if schema_type == "boolean":
            if isinstance(raw, bool):
                return raw
            text = str(raw).strip().casefold()
            if text in {"true", "1", "yes", "y", "on", "confirmed", "approve", "approved"}:
                return True
            if text in {"false", "0", "no", "n", "off", "deny", "denied"}:
                return False
            return bool(raw)
        return str(raw) if not isinstance(raw, (dict, list)) else raw

    def _as_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            out: list[Any] = []
            for item in value:
                if isinstance(item, list):
                    out.extend(item)
                elif not self._is_empty(item):
                    out.append(item)
            return out
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            # Generic separator handling for UI fields that return a single text
            # value for an array slot.  No capability-specific tokens are used.
            parts = [p.strip() for p in re.split(r"[;,\n]+", text) if p.strip()]
            return parts or [text]
        return [value]

    def _is_empty(self, value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}

    def _participant_id(self, participant: dict[str, Any]) -> str:
        return str(participant.get("participant_id") or participant.get("id") or "").strip()

    def _participant_name(self, participant: dict[str, Any]) -> str:
        return str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or self._participant_id(participant) or "participant").strip()

    def _safe_key(self, value: Any) -> str:
        return re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_")

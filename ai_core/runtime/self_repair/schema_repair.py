from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contracts import RepairAction


class SchemaRepairer:
    """Safe deterministic repairs for JSON-like payloads against simple schemas."""

    def plan(self, *, payload: dict[str, Any], schema: dict[str, Any]) -> list[RepairAction]:
        if not isinstance(payload, dict) or not isinstance(schema, dict):
            return []
        actions: list[RepairAction] = []
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key, spec in props.items():
            if key not in payload or not isinstance(spec, dict):
                continue
            old = payload.get(key)
            converted, changed = self._convert(old, spec)
            if changed:
                actions.append(RepairAction(
                    action_type="schema_type_coercion",
                    level="deterministic",
                    description=f"Coerce field '{key}' to declared schema type.",
                    target_path=key,
                    before=old,
                    after=converted,
                    safe_to_apply=True,
                    requires_validation=True,
                    confidence=0.92,
                ))
        return actions

    def apply(self, *, payload: dict[str, Any], actions: list[RepairAction]) -> dict[str, Any]:
        out = deepcopy(payload)
        for action in actions:
            if action.action_type == "schema_type_coercion" and action.target_path:
                out[action.target_path] = action.after
        return out

    def validate_minimal(self, *, payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(schema, dict):
            return {"passed": True, "status": "schema_not_provided"}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        errors: list[str] = []
        for key in required:
            if key not in payload or payload.get(key) in (None, ""):
                errors.append(f"missing_required:{key}")
        for key, spec in props.items():
            if key not in payload or not isinstance(spec, dict):
                continue
            expected = spec.get("type")
            if expected and not self._matches(payload.get(key), expected):
                errors.append(f"type_mismatch:{key}:{expected}")
        return {"passed": not errors, "errors": errors}

    def _convert(self, value: Any, spec: dict[str, Any]) -> tuple[Any, bool]:
        expected = spec.get("type")
        if isinstance(expected, list):
            expected = next((x for x in expected if x != "null"), expected[0] if expected else None)
        if expected == "array" and isinstance(value, str):
            parts = [p.strip() for p in value.split(",") if p.strip()]
            return (parts or [value], True)
        if expected == "string" and isinstance(value, list):
            return ("\n".join(str(x) for x in value if x is not None), True)
        if expected == "integer" and isinstance(value, str) and value.strip().isdigit():
            return (int(value.strip()), True)
        if expected == "number" and isinstance(value, str):
            try:
                return (float(value.strip()), True)
            except ValueError:
                return (value, False)
        if expected == "boolean" and isinstance(value, str):
            v = value.strip().casefold()
            if v in {"true", "yes", "1", "on"}:
                return (True, True)
            if v in {"false", "no", "0", "off"}:
                return (False, True)
        return (value, False)

    def _matches(self, value: Any, expected: Any) -> bool:
        if isinstance(expected, list):
            return any(self._matches(value, x) for x in expected)
        return {
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }.get(str(expected), True)

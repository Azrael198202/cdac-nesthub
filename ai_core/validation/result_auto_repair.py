from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ai_core.config.paths import RUNTIME_KNOWLEDGE


class ResultAutoRepair:
    """
    Generic runtime result repair.

    This repair layer is intentionally domain-neutral. It handles only structural
    schema problems that are safe to repair without asking the user:
    - missing required fields at any nested object level
    - null values where a concrete primitive/container type is required
    - common object/array/string/boolean/number shape normalization

    It does not invent domain facts. Unknown required values are filled with
    schema defaults or neutral structural placeholders so execution can continue
    and downstream validators/executors can decide whether the step is usable.
    """

    def __init__(self) -> None:
        self.log_path = RUNTIME_KNOWLEDGE / "result_auto_repair.jsonl"

    def try_repair(
        self,
        *,
        node_id: str,
        result: dict[str, Any],
        schema: dict[str, Any],
        state: dict[str, Any] | None,
        error_message: str,
    ) -> tuple[bool, dict[str, Any], list[str]]:
        if not isinstance(result, dict) or not isinstance(schema, dict):
            return False, result, []

        repaired = json.loads(json.dumps(result, ensure_ascii=False))
        changes: list[str] = []
        self._repair_value(
            value=repaired,
            schema=schema,
            state=state,
            path="root",
            changes=changes,
        )

        # Cross-field generic normalization retained from earlier versions.
        if "requires_human_review" not in repaired and isinstance(repaired.get("human_review"), dict):
            hr = repaired["human_review"]
            if "required" in hr:
                repaired["requires_human_review"] = bool(hr.get("required"))
                changes.append("root.requires_human_review.derived_from_human_review_required")

        if isinstance(repaired.get("requires_human_review"), dict):
            obj = repaired["requires_human_review"]
            if "human_review" not in repaired:
                repaired["human_review"] = obj
                changes.append("root.human_review.copied_from_requires_human_review_object")
            repaired["requires_human_review"] = self._truthy_object(obj)
            changes.append("root.requires_human_review.normalized_object_to_boolean")

        if changes:
            self._log({
                "created_at": datetime.utcnow().isoformat(),
                "node_id": node_id,
                "error_message": error_message,
                "changes": changes,
                "before": result,
                "after": repaired,
            })
            return True, repaired, changes

        return False, repaired, []

    def _repair_value(
        self,
        *,
        value: Any,
        schema: dict[str, Any],
        state: dict[str, Any] | None,
        path: str,
        changes: list[str],
    ) -> Any:
        if not isinstance(schema, dict):
            return value

        schema = self._select_schema(schema, value)
        typ = schema.get("type")
        if isinstance(typ, list):
            typ = self._preferred_type(typ)

        if value is None:
            default = self._default_from_schema(schema, self._field_name(path))
            changes.append(f"{path}.null_replaced")
            return default

        if typ == "object":
            if not isinstance(value, dict):
                default = self._default_from_schema(schema, self._field_name(path))
                changes.append(f"{path}.normalized_to_object")
                value = default if isinstance(default, dict) else {}
            self._repair_object(value, schema, state, path, changes)
            return value

        if typ == "array":
            if not isinstance(value, list):
                value = [] if value in ["", None] else [value]
                changes.append(f"{path}.normalized_to_array")
            item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
            for idx, item in enumerate(list(value)):
                value[idx] = self._repair_value(
                    value=item,
                    schema=item_schema,
                    state=state,
                    path=f"{path}[{idx}]",
                    changes=changes,
                )
            return value

        if typ == "string" and not isinstance(value, str):
            value = self._stringify(value)
            changes.append(f"{path}.normalized_to_string")
            return value

        if typ == "boolean" and not isinstance(value, bool):
            value = self._truthy(value)
            changes.append(f"{path}.normalized_to_boolean")
            return value

        if typ in {"number", "integer"} and not isinstance(value, (int, float)):
            value = self._number(value, integer=(typ == "integer"))
            changes.append(f"{path}.normalized_to_{typ}")
            return value

        return value

    def _repair_object(
        self, obj: dict[str, Any], schema: dict[str, Any], state: dict[str, Any] | None, path: str, changes: list[str]) -> None:
        props = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required", []) if isinstance(schema.get("required"), list) else []

        for field in required:
            if not isinstance(field, str):
                continue
            field_schema = props.get(field, {}) if isinstance(props.get(field, {}), dict) else {}
            if field not in obj or obj.get(field) is None:
                found, source = self._find_value(field, state)
                if found is None:
                    found = self._default_from_schema(field_schema, field)
                    source = "schema_default"
                obj[field] = found
                changes.append(f"{path}.{field}.filled_required_from_{source}")

        for field, field_schema in props.items():
            if field in obj and isinstance(field_schema, dict):
                repaired_child = self._repair_value(
                    value=obj.get(field),
                    schema=field_schema,
                    state=state,
                    path=f"{path}.{field}",
                    changes=changes,
                )
                obj[field] = repaired_child

    def _select_schema(self, schema: dict[str, Any], value: Any) -> dict[str, Any]:
        for key in ("oneOf", "anyOf"):
            options = schema.get(key)
            if isinstance(options, list) and options:
                for option in options:
                    if isinstance(option, dict) and self._value_matches_type(value, option.get("type")):
                        return option
                for option in options:
                    if isinstance(option, dict):
                        return option
        return schema

    def _value_matches_type(self, value: Any, typ: Any) -> bool:
        if isinstance(typ, list):
            return any(self._value_matches_type(value, t) for t in typ)
        if typ == "object":
            return isinstance(value, dict)
        if typ == "array":
            return isinstance(value, list)
        if typ == "string":
            return isinstance(value, str)
        if typ == "boolean":
            return isinstance(value, bool)
        if typ in {"number", "integer"}:
            return isinstance(value, (int, float))
        return False

    def _preferred_type(self, types: list[Any]) -> str | None:
        for t in ["object", "array", "string", "boolean", "number", "integer"]:
            if t in types:
                return t
        return str(types[0]) if types else None

    def _find_value(self, field: str, state: dict[str, Any] | None) -> tuple[Any, str]:
        if not state:
            return None, "none"
        for source_name in ("results", "human_feedback", "pending_action"):
            source_obj = state.get(source_name, {} if source_name != "human_feedback" else [])
            found = self._search_nested(source_obj, field)
            if found is not None:
                return found, source_name
        return None, "none"

    def _search_nested(self, obj: Any, field: str) -> Any:
        if isinstance(obj, dict):
            if field in obj and obj[field] not in [None, ""]:
                return obj[field]
            for value in obj.values():
                found = self._search_nested(value, field)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = self._search_nested(item, field)
                if found is not None:
                    return found
        return None

    def _default_from_schema(self, schema: dict[str, Any], field_name: str = "") -> Any:
        if not isinstance(schema, dict):
            return "unknown"
        if "default" in schema:
            return schema["default"]
        selected = self._select_schema(schema, None)
        typ = selected.get("type")
        if isinstance(typ, list):
            typ = self._preferred_type(typ)
        if typ == "object":
            default: dict[str, Any] = {}
            props = selected.get("properties", {}) if isinstance(selected.get("properties"), dict) else {}
            for req in selected.get("required", []) or []:
                if isinstance(req, str):
                    default[req] = self._default_from_schema(props.get(req, {}), req)
            return default
        if typ == "array":
            return []
        if typ == "boolean":
            return False
        if typ == "number":
            return 0
        if typ == "integer":
            return 0
        if typ == "string":
            if field_name == "next_action":
                return "continue"
            return "unknown"
        if "oneOf" in selected or "anyOf" in selected:
            return self._default_from_schema(self._select_schema(selected, None), field_name)
        return "unknown"

    def _field_name(self, path: str) -> str:
        clean = path.replace("]", "")
        part = clean.split(".")[-1]
        return part.split("[")[0]

    def _stringify(self, value: Any) -> str:
        if value is None:
            return "unknown"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _truthy(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "yes", "1", "required", "approve", "accepted"}
        return bool(value)

    def _truthy_object(self, obj: dict[str, Any]) -> bool:
        if "required" in obj:
            return self._truthy(obj.get("required"))
        if "status" in obj:
            return self._truthy(obj.get("status"))
        return bool(obj)

    def _number(self, value: Any, *, integer: bool) -> int | float:
        try:
            num = float(value)
        except Exception:
            num = 0.0
        return int(num) if integer else num

    def _log(self, record: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

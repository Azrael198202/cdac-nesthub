from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from ai_core.config.paths import RUNTIME_KNOWLEDGE


class ResultAutoRepair:
    """
    Generic runtime result repair.

    Purpose:
    - Fix model output when schema is correct but the model omitted required fields.
    - Do not weaken schema unnecessarily.
    - Prefer copying missing values from previous_results.
    - If no source exists, use safe schema-based placeholders.

    This is generic and node-agnostic.
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
        if not isinstance(result, dict):
            return False, result, []

        repaired = json.loads(json.dumps(result, ensure_ascii=False))
        changes: list[str] = []

        missing_required = self._extract_missing_required(error_message)
        if not missing_required:
            missing_required = [
                field for field in schema.get("required", [])
                if isinstance(field, str) and field not in repaired
            ]

        for field in missing_required:
            if field in repaired:
                continue

            value, source = self._find_value(field, state)
            if value is None:
                value = self._default_value_for_field(field, schema)
                source = "schema_default"

            repaired[field] = value
            changes.append(f"filled_missing_required.{field}.from_{source}")

        # Additional generic normalization:
        # If human_review exists but requires_human_review is missing, derive boolean.
        if "requires_human_review" not in repaired and isinstance(repaired.get("human_review"), dict):
            hr = repaired["human_review"]
            if "required" in hr:
                repaired["requires_human_review"] = bool(hr.get("required"))
                changes.append("derived.requires_human_review.from_human_review.required")

        # If requires_human_review is object and schema still wants boolean,
        # derive boolean while keeping human_review.
        if isinstance(repaired.get("requires_human_review"), dict):
            obj = repaired["requires_human_review"]
            if "human_review" not in repaired:
                repaired["human_review"] = obj
                changes.append("copied.requires_human_review_object.to_human_review")

            if "required" in obj:
                repaired["requires_human_review"] = bool(obj.get("required"))
            elif str(obj.get("status", "")).lower() in {"required", "true", "yes"}:
                repaired["requires_human_review"] = True
            else:
                repaired["requires_human_review"] = False
            changes.append("normalized.requires_human_review.object_to_boolean")

        changed = bool(changes)
        if changed:
            self._log({
                "created_at": datetime.utcnow().isoformat(),
                "node_id": node_id,
                "error_message": error_message,
                "changes": changes,
                "before": result,
                "after": repaired,
            })

        return changed, repaired, changes

    def _extract_missing_required(self, error_message: str) -> list[str]:
        # jsonschema message:
        # 'intent_type' is a required property
        matches = re.findall(r"'([^']+)'\s+is a required property", error_message)
        return list(dict.fromkeys(matches))

    def _find_value(self, field: str, state: dict[str, Any] | None) -> tuple[Any, str]:
        if not state:
            return None, "none"

        # 1. Search previous node results.
        results = state.get("results", {})
        found = self._search_nested(results, field)
        if found is not None:
            return found, "previous_results"

        # 2. Search human feedback original outputs.
        for item in state.get("human_feedback", []) or []:
            found = self._search_nested(item, field)
            if found is not None:
                return found, "human_feedback"

        # 3. Search pending action.
        found = self._search_nested(state.get("pending_action", {}), field)
        if found is not None:
            return found, "pending_action"

        return None, "none"

    def _search_nested(self, obj: Any, field: str) -> Any:
        if isinstance(obj, dict):
            if field in obj and obj[field] not in [None, ""]:
                return obj[field]
            for value in obj.values():
                found = self._search_nested(value, field)
                if found is not None:
                    return found

        if isinstance(obj, list):
            for item in obj:
                found = self._search_nested(item, field)
                if found is not None:
                    return found

        return None

    def _default_value_for_field(self, field: str, schema: dict[str, Any]) -> Any:
        props = schema.get("properties", {})
        field_schema = props.get(field, {})
        return self._default_from_schema(field_schema, field)

    def _default_from_schema(self, field_schema: dict[str, Any], field_name: str = "") -> Any:
        if "default" in field_schema:
            return field_schema["default"]

        typ = field_schema.get("type")

        if isinstance(typ, list):
            if "string" in typ:
                return "unknown"
            if "number" in typ:
                return 0
            if "boolean" in typ:
                return False
            if "array" in typ:
                return []
            if "object" in typ:
                return {}

        if typ == "string":
            if field_name == "intent_type":
                return "unknown_intent"
            return "unknown"

        if typ == "number":
            return 0

        if typ == "boolean":
            return False

        if typ == "array":
            return []

        if typ == "object":
            return {}

        if "anyOf" in field_schema:
            for candidate in field_schema["anyOf"]:
                if candidate.get("type") == "string":
                    return "unknown"
            return self._default_from_schema(field_schema["anyOf"][0], field_name)

        return "unknown"

    def _log(self, record: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

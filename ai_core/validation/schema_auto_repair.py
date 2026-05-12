from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_KNOWLEDGE


class SchemaAutoRepair:
    """
    Generic runtime schema repair.

    Purpose:
    - If model output is structurally better than the old schema, evolve schema automatically.
    - Avoid blocking workflow for safe schema compatibility changes.

    This is node-agnostic and field-agnostic.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.log_path = RUNTIME_KNOWLEDGE / "schema_auto_repair.jsonl"

    def try_repair(
        self,
        *,
        node_id: str,
        schema_path: str,
        schema: dict[str, Any],
        result: dict[str, Any],
        error_message: str,
    ) -> tuple[bool, dict[str, Any], list[str]]:
        changes: list[str] = []
        repaired = json.loads(json.dumps(schema))

        field = self._extract_property_field(error_message)
        if field and isinstance(result, dict) and field in result:
            actual_schema = self._infer_schema(result[field])
            if self._make_property_compatible(repaired, field, actual_schema):
                changes.append(f"schema.properties.{field}.compatible_with_actual_output")

        # Common structured confidence evolution.
        if isinstance(result, dict) and isinstance(result.get("confidence"), dict):
            confidence_schema = {
                "type": "object",
                "properties": {
                    "overall": {"type": "number"},
                    "intent": {"type": "number"},
                    "parameters": {"type": "number"},
                    "execution_readiness": {"type": "number"},
                },
                "additionalProperties": True,
            }
            if self._make_property_compatible(repaired, "confidence", confidence_schema):
                changes.append("schema.confidence.number_or_object")

        # Common human review evolution.
        if isinstance(result, dict) and isinstance(result.get("human_review"), dict):
            human_review_schema = {
                "type": "object",
                "properties": {
                    "required": {"type": "boolean"},
                    "review_stage": {"type": "string"},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": True,
            }
            if self._ensure_property(repaired, "human_review", human_review_schema):
                changes.append("schema.human_review.object")

        # Common executable task object evolution.
        if isinstance(result, dict) and isinstance(result.get("tasks"), list):
            tasks = result.get("tasks") or []
            if any(isinstance(x, dict) for x in tasks):
                task_schema = {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string"},
                            "task_type": {"type": "string"},
                            "action": {"type": "string"},
                            "capability_action": {"type": "string"},
                            "parameters": {"type": "object"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                            "requires_human_confirmation": {"type": "boolean"},
                            "execution_ready": {"type": "boolean"},
                        },
                        "additionalProperties": True,
                    },
                }
                # Do not require all keys here; automatic repair should be compatibility-oriented.
                if self._make_property_compatible(repaired, "tasks", task_schema):
                    changes.append("schema.tasks.object_array_compatible")

        changed = bool(changes)
        if changed:
            self.loader.save_json(schema_path, repaired)
            self._log({
                "created_at": datetime.utcnow().isoformat(),
                "node_id": node_id,
                "schema_path": schema_path,
                "error_message": error_message,
                "changes": changes,
            })

        return changed, repaired, changes

    def _extract_property_field(self, error_message: str) -> str | None:
        # jsonschema error usually contains:
        # schema['properties']['confidence']
        m = re.search(r"schema\['properties'\]\['([^']+)'\]", error_message)
        if m:
            return m.group(1)

        # Alternative:
        # On instance['confidence']:
        m = re.search(r"instance\['([^']+)'\]", error_message)
        if m:
            return m.group(1)

        return None

    def _infer_schema(self, value: Any) -> dict[str, Any]:
        if isinstance(value, bool):
            return {"type": "boolean"}
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return {"type": "number"}
        if isinstance(value, str):
            return {"type": "string"}
        if isinstance(value, list):
            item_schema = {"additionalProperties": True}
            for item in value:
                item_schema = self._infer_schema(item)
                break
            return {"type": "array", "items": item_schema}
        if isinstance(value, dict):
            props = {}
            for k, v in value.items():
                props[k] = self._infer_schema(v)
            return {"type": "object", "properties": props, "additionalProperties": True}
        if value is None:
            return {"type": "null"}
        return {"type": ["string", "number", "boolean", "object", "array", "null"]}

    def _ensure_property(self, schema: dict[str, Any], field: str, field_schema: dict[str, Any]) -> bool:
        props = schema.setdefault("properties", {})
        if field not in props:
            props[field] = field_schema
            return True
        return False

    def _make_property_compatible(self, schema: dict[str, Any], field: str, actual_schema: dict[str, Any]) -> bool:
        props = schema.setdefault("properties", {})
        current = props.get(field)

        if current is None:
            props[field] = actual_schema
            return True

        if self._schema_accepts(current, actual_schema):
            return False

        any_of = []
        if "anyOf" in current and isinstance(current["anyOf"], list):
            any_of.extend(current["anyOf"])
        else:
            any_of.append(current)

        if not any(self._schemas_equal(x, actual_schema) for x in any_of):
            any_of.append(actual_schema)

        props[field] = {"anyOf": any_of}
        return True

    def _schema_accepts(self, current: dict[str, Any], actual: dict[str, Any]) -> bool:
        if self._schemas_equal(current, actual):
            return True

        current_type = current.get("type")
        actual_type = actual.get("type")

        if isinstance(current_type, list) and actual_type in current_type:
            return True

        if current_type == actual_type:
            return True

        if "anyOf" in current:
            return any(self._schema_accepts(x, actual) for x in current.get("anyOf", []))

        return False

    def _schemas_equal(self, a: dict[str, Any], b: dict[str, Any]) -> bool:
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def _log(self, record: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

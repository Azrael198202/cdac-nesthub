from __future__ import annotations

import re
from typing import Any


class QuestionGenerator:
    """Generates generic human-input requests from runtime missing-field metadata.

    This class intentionally contains no domain-specific field list. It only
    converts field metadata that already exists in the runtime-generated workflow
    into a frontend-renderable interaction contract.
    """

    def build_request(self, interactions: list[dict[str, Any]]) -> dict[str, Any]:
        fields: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for interaction in interactions:
            step_id = str(interaction.get("step_id", ""))
            objective = interaction.get("objective")
            for raw_field in interaction.get("fields", []) or []:
                field = self._normalize_field(raw_field, step_id=step_id)
                key = (field.get("step_id", ""), field.get("field", ""))
                if not key[1] or key in seen:
                    continue
                seen.add(key)
                if objective and not field.get("description"):
                    field["description"] = str(objective)
                fields.append(field)

        return {
            "kind": "human_information_required",
            "type": "form",
            "status": "waiting_for_user_input",
            "title": "Additional information required",
            "message": "Additional information is required before the workflow can continue.",
            "fields": fields,
            "submit_label": "Save information & continue",
            "cancel_label": "Cancel workflow",
            "expected_response_format": {
                "answers": {
                    "<field name>": "<value>"
                }
            },
            "resume_strategy": {
                "type": "resume_workflow",
                "merge_target": "workflow_planning",
            },
        }

    def _normalize_field(self, raw_field: Any, *, step_id: str) -> dict[str, Any]:
        if isinstance(raw_field, dict):
            field_name = self._first_text(
                raw_field,
                ["field", "field_id", "name", "id", "key", "parameter", "parameter_name"],
            )
            label = self._first_text(raw_field, ["label", "title", "question"])
            field_type = self._first_text(raw_field, ["type", "input_type", "ui_type"]) or self._infer_type(field_name)
            options = raw_field.get("options") or raw_field.get("choices") or raw_field.get("enum")
            normalized = {
                "step_id": str(raw_field.get("step_id") or step_id),
                "field": field_name,
                "label": label or self._label(field_name),
                "question": raw_field.get("question") or self._question(field_name),
                "type": field_type,
                "required": bool(raw_field.get("required", True)),
            }
            if raw_field.get("description"):
                normalized["description"] = str(raw_field.get("description"))
            if isinstance(options, list) and options:
                normalized["options"] = [str(x) for x in options]
                if normalized["type"] in {"text", "string"}:
                    normalized["type"] = "select"
            if raw_field.get("placeholder"):
                normalized["placeholder"] = str(raw_field.get("placeholder"))
            return normalized

        field_name = str(raw_field).strip()
        return {
            "step_id": step_id,
            "field": field_name,
            "label": self._label(field_name),
            "question": self._question(field_name),
            "type": self._infer_type(field_name),
            "required": True,
        }

    def _first_text(self, data: dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _label(self, field_name: str) -> str:
        label = str(field_name or "").replace("_", " ").replace("-", " ").strip()
        label = re.sub(r"\s+", " ", label)
        return label[:1].upper() + label[1:] if label else "Required value"

    def _question(self, field_name: str) -> str:
        return f"Please provide: {self._label(field_name)}."

    def _infer_type(self, field_name: str) -> str:
        # Generic heuristic based on the field name text. This is not domain
        # logic; it only helps render a reasonable HTML input type.
        name = str(field_name or "").lower()
        if "date" in name:
            return "date"
        if "time" in name:
            return "time"
        if any(token in name for token in ["count", "number", "amount", "quantity", "passenger"]):
            return "number"
        if any(token in name for token in ["email"]):
            return "email"
        return "text"

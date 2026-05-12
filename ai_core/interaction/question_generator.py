from __future__ import annotations

from typing import Any


class QuestionGenerator:
    """Generates generic human-input requests from missing field metadata."""

    def build_request(self, interactions: list[dict[str, Any]]) -> dict[str, Any]:
        fields: list[dict[str, Any]] = []
        for interaction in interactions:
            step_id = str(interaction.get("step_id", ""))
            for field in interaction.get("fields", []) or []:
                field_name = str(field)
                fields.append({
                    "step_id": step_id,
                    "field": field_name,
                    "question": self._question(field_name),
                    "required": True,
                })

        return {
            "kind": "human_information_required",
            "status": "waiting_for_user_input",
            "message": "Additional information is required before the workflow can continue.",
            "fields": fields,
            "expected_response_format": {
                "answers": {
                    "<field name>": "<value>"
                }
            },
        }

    def _question(self, field_name: str) -> str:
        label = field_name.replace("_", " ").strip()
        return f"Please provide: {label}."

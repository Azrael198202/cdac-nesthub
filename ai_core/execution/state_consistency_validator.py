from __future__ import annotations

from copy import deepcopy
from typing import Any


class ExecutionStateConsistencyValidator:
    """Validate and repair generic execution-state inconsistencies.

    The validator is intentionally domain-neutral. It only checks structural
    contradictions such as a step being marked as needing human input when no
    missing fields or confirmation requirements exist.
    """

    def repair_step(self, step: dict[str, Any]) -> dict[str, Any]:
        repaired = deepcopy(step or {})
        params = repaired.get("parameters") if isinstance(repaired.get("parameters"), dict) else {}
        missing_required = params.get("missing_required")
        missing_fields = self.missing_fields(repaired)
        requires_confirmation = self.requires_confirmation(repaired)
        execution_ready = bool(repaired.get("execution_ready", False))

        if execution_ready and not missing_fields and not requires_confirmation:
            # A ready, non-confirmation step must not carry active human input
            # metadata. Preserve the slot but make the state explicit.
            repaired["human_interaction"] = {
                "required": False,
                "type": "none",
                "fields": {},
            }
            repaired["missing_fields"] = []
            if isinstance(params, dict):
                if isinstance(missing_required, list):
                    params["missing_required"] = []
                elif isinstance(missing_required, dict):
                    params["missing_required"] = {}
                repaired["parameters"] = params
            repaired["execution_state_consistency"] = {
                "status": "repaired",
                "reason": "ready_step_must_not_request_human_information",
            }
        return repaired

    def should_request_human_information(self, step: dict[str, Any], human_interaction: dict[str, Any]) -> bool:
        if self.requires_confirmation(step):
            return False
        missing_fields = self.missing_fields(step)
        if missing_fields:
            return True
        fields = human_interaction.get("fields")
        if self._has_fields(fields) and bool(human_interaction.get("required")):
            return True
        return False

    def should_request_confirmation(self, step: dict[str, Any]) -> bool:
        return self.requires_confirmation(step)

    def missing_fields(self, step: dict[str, Any]) -> list[str]:
        explicit = step.get("missing_fields")
        values: list[str] = []
        if isinstance(explicit, list):
            values.extend(str(x) for x in explicit if str(x).strip())

        params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        raw = params.get("missing_required")
        if isinstance(raw, list):
            values.extend(str(x) for x in raw if str(x).strip())
        elif isinstance(raw, dict):
            for key, value in raw.items():
                if value not in [None, "", [], {}]:
                    # Some LLMs put full field metadata objects here. In that
                    # shape the key is still missing, because a description is
                    # not a supplied value.
                    if isinstance(value, dict) and any(k in value for k in ["label", "question", "placeholder", "example", "type"]):
                        values.append(str(key))
                else:
                    values.append(str(key))
        return list(dict.fromkeys(v for v in values if v.strip()))

    def requires_confirmation(self, step: dict[str, Any]) -> bool:
        if bool(step.get("requires_human_confirmation", False)):
            return True
        hi = step.get("human_interaction") if isinstance(step.get("human_interaction"), dict) else {}
        hi_type = str(hi.get("type") or "").lower().strip()
        if hi_type in {"confirmation", "human_confirmation", "approval"} and bool(hi.get("required", True)):
            return True
        return False

    def _has_fields(self, value: Any) -> bool:
        if isinstance(value, dict):
            return bool(value)
        if isinstance(value, list):
            return bool(value)
        return False

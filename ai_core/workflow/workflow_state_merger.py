from __future__ import annotations

from copy import deepcopy
from typing import Any


class WorkflowStateMerger:
    """Merges human-provided values into runtime-generated workflow state."""

    def merge_human_information(self, workflow_plan: dict[str, Any], human_payload: dict[str, Any]) -> dict[str, Any]:
        plan = deepcopy(workflow_plan or {})
        answers = self._extract_answers(human_payload)
        if not answers:
            return plan

        for step in plan.get("planned_steps", []) or []:
            if not isinstance(step, dict):
                continue
            params = step.setdefault("parameters", {})
            if not isinstance(params, dict):
                step["parameters"] = params = {"known": {}, "missing_required": {}, "optional": {}}
            known = params.setdefault("known", {})
            missing = params.setdefault("missing_required", {})

            if isinstance(missing, dict):
                for field in list(missing.keys()):
                    matched_key = self._find_answer_key(field, answers)
                    if matched_key and answers[matched_key] not in [None, "", [], {}]:
                        known[field] = answers[matched_key]
                        missing.pop(field, None)
            elif isinstance(missing, list):
                remaining = []
                for field in missing:
                    field_name = str(field)
                    matched_key = self._find_answer_key(field_name, answers)
                    if matched_key and answers[matched_key] not in [None, "", [], {}]:
                        known[field_name] = answers[matched_key]
                    else:
                        remaining.append(field)
                params["missing_required"] = remaining

            step["missing_fields"] = self._missing_fields(params)
            step["execution_ready"] = not bool(step["missing_fields"])

        plan["blocking_missing_information"] = self._collect_missing(plan)
        plan.setdefault("continuation", {})["last_merge"] = {
            "status": "merged_human_information",
            "answer_fields": list(answers.keys()),
        }
        return plan

    def _extract_answers(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        raw = payload.get("answers", payload)
        if not isinstance(raw, dict):
            return {}
        result: dict[str, Any] = {}
        for key, value in raw.items():
            if isinstance(value, dict) and "value" in value:
                result[str(key)] = value.get("value")
            else:
                result[str(key)] = value
        return result

    def _find_answer_key(self, field: str, answers: dict[str, Any]) -> str | None:
        candidates = {field, self._safe_key(field)}
        for key in answers.keys():
            if key in candidates or self._safe_key(key) in candidates:
                return key
        return None

    def _safe_key(self, value: str) -> str:
        chars = []
        for ch in str(value or "").lower():
            chars.append(ch if ch.isalnum() else "_")
        return "_".join(part for part in "".join(chars).split("_") if part)

    def _missing_fields(self, params: dict[str, Any]) -> list[str]:
        raw = params.get("missing_required")
        if isinstance(raw, list):
            return [str(x) for x in raw if str(x).strip()]
        if isinstance(raw, dict):
            return [str(k) for k, v in raw.items() if v in [None, "", [], {}]]
        return []

    def _collect_missing(self, plan: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for step in plan.get("planned_steps", []) or []:
            if isinstance(step, dict):
                missing.extend(step.get("missing_fields") or [])
        return list(dict.fromkeys(str(x) for x in missing))

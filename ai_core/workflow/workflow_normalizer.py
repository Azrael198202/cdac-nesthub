from __future__ import annotations

from copy import deepcopy
from typing import Any


class WorkflowNormalizer:
    """
    Normalizes runtime-generated workflow plans without knowing domain semantics.

    The normalizer only uses generic structural fields and token similarity between
    runtime-provided strings. It never hardcodes task types, actions, or capability
    names.
    """

    def normalize(self, workflow_plan: dict[str, Any]) -> dict[str, Any]:
        plan = deepcopy(workflow_plan or {})
        steps = plan.get("planned_steps") or plan.get("tasks") or []
        if not isinstance(steps, list):
            steps = []

        global_capabilities = self._as_string_list(plan.get("required_capabilities"))
        normalized_steps: list[dict[str, Any]] = []

        for index, raw_step in enumerate(steps):
            if not isinstance(raw_step, dict):
                continue

            step = deepcopy(raw_step)
            step_id = step.get("step_id") or step.get("task_id") or f"step_{index + 1}"
            step["step_id"] = str(step_id)
            step.setdefault("task_id", str(step_id))

            parameters = self._normalize_parameters(step.get("parameters"))
            step["parameters"] = parameters
            step["missing_fields"] = self._missing_fields_from_parameters(parameters)

            step_capability = self._extract_step_capability(step)
            if not step_capability:
                step_capability = self._match_capability(step, global_capabilities)
            if step_capability:
                step["required_capability"] = step_capability

            if "execution_ready" not in step:
                step["execution_ready"] = not bool(step["missing_fields"])

            step.setdefault("depends_on", [])
            step.setdefault("requires_human_confirmation", False)
            normalized_steps.append(step)

        plan["planned_steps"] = normalized_steps
        plan["blocking_missing_information"] = self._collect_missing_info(plan, normalized_steps)
        plan["required_capabilities"] = global_capabilities
        plan["normalization"] = {
            "status": "normalized",
            "step_count": len(normalized_steps),
            "capability_mapping_strategy": "runtime_string_similarity",
        }
        return plan

    def _normalize_parameters(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"known": {}, "missing_required": {}, "optional": {}}

        if any(k in value for k in ["known", "missing_required", "optional"]):
            return {
                "known": value.get("known") if isinstance(value.get("known"), dict) else {},
                "missing_required": value.get("missing_required") if isinstance(value.get("missing_required"), (dict, list)) else {},
                "optional": value.get("optional") if isinstance(value.get("optional"), dict) else {},
            }

        return {
            "known": deepcopy(value),
            "missing_required": {},
            "optional": {},
        }

    def _collect_missing_info(self, plan: dict[str, Any], steps: list[dict[str, Any]]) -> list[str]:
        values = self._as_string_list(plan.get("blocking_missing_information"))
        values.extend(self._as_string_list(plan.get("missing_information")))
        for step in steps:
            values.extend(self._as_string_list(step.get("missing_fields")))
        return list(dict.fromkeys(values))

    def _extract_step_capability(self, step: dict[str, Any]) -> str | None:
        for key in ["required_capability", "capability"]:
            value = step.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                for nested_key in ["capability", "capability_id", "capability_action", "action", "name", "id"]:
                    nested = value.get(nested_key)
                    if isinstance(nested, str) and nested.strip():
                        return nested.strip()

        values = step.get("required_capabilities")
        if isinstance(values, list) and values:
            first = values[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                nested = first.get("capability") or first.get("capability_id") or first.get("capability_action") or first.get("action") or first.get("name") or first.get("id")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
        return None

    def _match_capability(self, step: dict[str, Any], capabilities: list[str]) -> str | None:
        if not capabilities:
            return None
        if len(capabilities) == 1:
            return capabilities[0]

        source_text = " ".join(
            str(step.get(k, "")) for k in ["task_type", "action", "name", "objective", "description"]
        )
        source_tokens = self._tokens(source_text)
        if not source_tokens:
            return None

        best_capability: str | None = None
        best_score = 0.0
        for capability in capabilities:
            capability_tokens = self._tokens(capability)
            if not capability_tokens:
                continue
            overlap = len(source_tokens.intersection(capability_tokens))
            score = overlap / max(len(capability_tokens), 1)
            if score > best_score:
                best_score = score
                best_capability = capability

        return best_capability if best_score > 0 else None

    def _missing_fields_from_parameters(self, parameters: dict[str, Any]) -> list[str]:
        raw = parameters.get("missing_required")
        missing: list[str] = []
        if isinstance(raw, list):
            missing.extend(str(x) for x in raw if str(x).strip())
        elif isinstance(raw, dict):
            for key, value in raw.items():
                if value in [None, "", [], {}]:
                    missing.append(str(key))
        return list(dict.fromkeys(missing))

    def _as_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, dict):
                candidate = item.get("capability") or item.get("capability_id") or item.get("capability_action") or item.get("action") or item.get("name") or item.get("id")
                if isinstance(candidate, str) and candidate.strip():
                    result.append(candidate.strip())
        return list(dict.fromkeys(result))

    def _tokens(self, value: str) -> set[str]:
        chars = []
        for ch in value.lower():
            chars.append(ch if ch.isalnum() else " ")
        return {token for token in "".join(chars).split() if token}

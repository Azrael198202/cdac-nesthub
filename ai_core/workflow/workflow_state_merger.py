from __future__ import annotations

from copy import deepcopy
from typing import Any


class WorkflowStateMerger:
    """Merges human-provided values into runtime-generated workflow state.

    The merger is intentionally domain-neutral. It does not infer meaning from
    field names. It only uses exact keys, normalized keys, and merge metadata
    produced by runtime/LLM interaction contracts.
    """

    def merge_human_information(
        self,
        workflow_plan: dict[str, Any],
        human_payload: dict[str, Any],
        *,
        interaction_request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plan = deepcopy(workflow_plan or {})
        answers = self._extract_answers(human_payload)
        if not answers:
            return plan

        mapping = self._extract_mapping(human_payload, interaction_request)
        answer_aliases = self._answer_aliases(answers, mapping)

        for step in plan.get("planned_steps", []) or []:
            if not isinstance(step, dict):
                continue

            step_id = str(step.get("step_id") or step.get("task_id") or "")
            params = step.setdefault("parameters", {})
            if not isinstance(params, dict):
                step["parameters"] = params = {"known": {}, "missing_required": {}, "optional": {}}

            known = params.setdefault("known", {})
            if not isinstance(known, dict):
                params["known"] = known = {}

            missing = params.setdefault("missing_required", {})
            if isinstance(missing, dict):
                self._merge_missing_dict(missing, known, answers, answer_aliases, step_id)
            elif isinstance(missing, list):
                params["missing_required"] = self._merge_missing_list(missing, known, answers, answer_aliases, step_id)

            self._merge_explicit_step_answers(known, answers, answer_aliases, step_id)

            step["missing_fields"] = self._missing_fields(params)
            step["execution_ready"] = not bool(step["missing_fields"])

        plan["blocking_missing_information"] = self._collect_missing(plan)
        plan.setdefault("continuation", {})["last_merge"] = {
            "status": "merged_human_information",
            "answer_fields": list(answers.keys()),
            "mapped_fields": sorted(answer_aliases.keys()),
            "remaining_missing_information": plan.get("blocking_missing_information", []),
        }
        return plan

    def _merge_missing_dict(
        self,
        missing: dict[str, Any],
        known: dict[str, Any],
        answers: dict[str, Any],
        answer_aliases: dict[str, dict[str, Any]],
        step_id: str,
    ) -> None:
        for field in list(missing.keys()):
            matched_key = self._find_answer_key(field, answer_aliases, step_id)
            if matched_key and self._has_value(answers.get(matched_key)):
                known[field] = answers[matched_key]
                missing.pop(field, None)

    def _merge_missing_list(
        self,
        missing: list[Any],
        known: dict[str, Any],
        answers: dict[str, Any],
        answer_aliases: dict[str, dict[str, Any]],
        step_id: str,
    ) -> list[Any]:
        remaining = []
        for field in missing:
            field_name = str(field)
            matched_key = self._find_answer_key(field_name, answer_aliases, step_id)
            if matched_key and self._has_value(answers.get(matched_key)):
                known[field_name] = answers[matched_key]
            else:
                remaining.append(field)
        return remaining

    def _merge_explicit_step_answers(
        self,
        known: dict[str, Any],
        answers: dict[str, Any],
        answer_aliases: dict[str, dict[str, Any]],
        step_id: str,
    ) -> None:
        """Keep provided values in known even when there is no missing match.

        This is generic and safe because it only applies answers whose mapping
        says they belong to the current step, or answers with no step mapping.
        It does not clear missing_required unless a mapped alias matches it.
        """
        for answer_key, value in answers.items():
            if not self._has_value(value):
                continue
            meta = answer_aliases.get(answer_key, {})
            mapped_step = str(meta.get("step_id") or "")
            if mapped_step and step_id and mapped_step != step_id:
                continue
            target = str(meta.get("source_field") or answer_key)
            if target:
                known.setdefault(target, value)

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

    def _extract_mapping(
        self,
        payload: dict[str, Any],
        interaction_request: dict[str, Any] | None,
    ) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        if isinstance(interaction_request, dict):
            request_mapping = interaction_request.get("field_mapping")
            if isinstance(request_mapping, dict):
                mapping.update(request_mapping)
            for field in interaction_request.get("fields", []) or []:
                if isinstance(field, dict):
                    field_id = str(field.get("field") or "").strip()
                    if field_id:
                        mapping.setdefault(field_id, field)
        if isinstance(payload, dict):
            payload_mapping = payload.get("field_mapping")
            if isinstance(payload_mapping, dict):
                mapping.update(payload_mapping)
            request = payload.get("interaction_request")
            if isinstance(request, dict):
                request_mapping = request.get("field_mapping")
                if isinstance(request_mapping, dict):
                    mapping.update(request_mapping)
        return mapping

    def _answer_aliases(self, answers: dict[str, Any], mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for answer_key in answers.keys():
            meta = mapping.get(answer_key, {}) if isinstance(mapping, dict) else {}
            if not isinstance(meta, dict):
                meta = {}

            aliases: list[str] = [answer_key]
            for key in ["source_field", "field", "original_field", "merge_field"]:
                value = meta.get(key)
                if isinstance(value, str) and value.strip():
                    aliases.append(value.strip())

            raw_aliases = meta.get("aliases") or meta.get("merge_aliases")
            if isinstance(raw_aliases, list):
                aliases.extend(str(x).strip() for x in raw_aliases if str(x).strip())

            raw_targets = meta.get("merge_targets")
            if isinstance(raw_targets, list):
                for target in raw_targets:
                    if isinstance(target, dict):
                        value = target.get("source_field")
                        if isinstance(value, str) and value.strip():
                            aliases.append(value.strip())

            result[answer_key] = {
                "step_id": str(meta.get("step_id") or ""),
                "source_field": str(meta.get("source_field") or answer_key),
                "aliases": self._normalized_aliases(aliases),
            }
        return result

    def _find_answer_key(self, field: str, answer_aliases: dict[str, dict[str, Any]], step_id: str) -> str | None:
        normalized_field = self._safe_key(field)
        for answer_key, meta in answer_aliases.items():
            mapped_step = str(meta.get("step_id") or "")
            if mapped_step and step_id and mapped_step != step_id:
                continue
            aliases = meta.get("aliases") or set()
            if normalized_field in aliases:
                return answer_key
        return None

    def _normalized_aliases(self, aliases: list[str]) -> set[str]:
        result: set[str] = set()
        for alias in aliases:
            key = self._safe_key(alias)
            if key:
                result.add(key)
        return result

    def _safe_key(self, value: str) -> str:
        chars = []
        for ch in str(value or "").lower():
            chars.append(ch if ch.isalnum() else "_")
        return "_".join(part for part in "".join(chars).split("_") if part)

    def _has_value(self, value: Any) -> bool:
        return value not in [None, "", [], {}]

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

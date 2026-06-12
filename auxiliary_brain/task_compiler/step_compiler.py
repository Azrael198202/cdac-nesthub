from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re

from .prompt_compiler import PromptProfileCompiler


@dataclass
class StepCompiler:
    prompt_compiler: PromptProfileCompiler = field(default_factory=PromptProfileCompiler)

    def compile_steps(self, task_graph: dict[str, Any]) -> list[dict[str, Any]]:
        raw_steps = task_graph.get("tasks") if isinstance(task_graph.get("tasks"), list) else []
        schedule_policy = task_graph.get("schedule_policy") if isinstance(task_graph.get("schedule_policy"), dict) else {}
        controller_ids = {str(x).strip() for x in (schedule_policy.get("controller_participant_ids") or []) if str(x).strip()}
        payload_steps = [raw for raw in raw_steps if isinstance(raw, dict) and str(raw.get("participant_id") or raw.get("id") or "").strip() not in controller_ids]
        compiled: list[dict[str, Any]] = []
        for index, raw in enumerate(payload_steps, start=1):
            if not isinstance(raw, dict):
                continue
            original_step_id = str(raw.get("source_step_id") or raw.get("step_id") or "").strip()
            step_id = f"step_{index:03d}" if controller_ids else (original_step_id or f"step_{index:03d}")
            instruction = str(raw.get("source_instruction_fragment") or raw.get("instruction") or raw.get("execution_objective") or raw.get("objective") or "").strip()
            source_contract = self._source_contract(raw, instruction)
            raw_for_profile = {**raw, "source_contract": source_contract}
            prompt_profile = self.prompt_compiler.compile_for_step(raw_for_profile)
            execution_contract = self._execution_contract(raw_for_profile, prompt_profile)
            presentation_contract = self._presentation_contract(raw)
            binding_contract = self._binding_contract(raw)
            known_state = self._known_state(raw, source_contract, instruction)
            compiled.append({
                "step_id": step_id,
                "step_index": index,
                "step_name": str(raw.get("display_name") or raw.get("participant_display_name") or raw.get("name") or step_id),
                "participant_id": str(raw.get("participant_id") or raw.get("id") or step_id),
                "instruction": instruction,
                "depends_on": self._normalize_depends_on(raw.get("depends_on")),
                "prompt_profile": prompt_profile,
                "execution_contract": execution_contract,
                "source_contract": source_contract,
                "execution_known": known_state["execution_known"],
                "semantic_known": known_state["semantic_known"],
                "task_metadata": known_state["task_metadata"],
                "presentation_contract": presentation_contract,
                "binding_contract": binding_contract,
                "context_contract": {
                    "task_context_inheritance": True,
                    "sibling_step_context_inheritance": False,
                    "task_session_id_field": "task_session_id",
                    "step_execution_id_field": "step_execution_id",
                },
                "raw_step_ref": {
                    "participant_id": str(raw.get("participant_id") or raw.get("id") or ""),
                    "source_step_id": str(raw.get("source_step_id") or ""),
                    "original_step_id": original_step_id,
                },
            })
        return compiled

    def _normalize_depends_on(self, raw: Any) -> list[str]:
        out: list[str] = []
        for item in raw or []:
            value = self._dependency_ref_value(item)
            if not value:
                continue
            canonical = self._normalize_step_ref(value)
            if canonical and canonical not in out:
                out.append(canonical)
        return out

    def _dependency_ref_value(self, item: Any) -> str:
        if isinstance(item, dict):
            for key in ("id", "step_id", "source_step_id", "participant_id", "name"):
                value = str(item.get(key) or "").strip()
                if value:
                    return value
            return ""
        return str(item or "").strip()

    def _normalize_step_ref(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        match = re.fullmatch(r"(?:step|stage)?\s*_?\s*(\d+)", text, flags=re.I)
        if match:
            return f"step_{int(match.group(1)):03d}"
        match = re.fullmatch(r"step[_-](\d+)", text, flags=re.I)
        if match:
            return f"step_{int(match.group(1)):03d}"
        return text

    def _known_state(self, raw: dict[str, Any], source_contract: dict[str, Any], instruction: str) -> dict[str, Any]:
        execution_known: dict[str, Any] = {}
        cardinality = source_contract.get("output_cardinality") if isinstance(source_contract.get("output_cardinality"), dict) else {}
        requested_count = cardinality.get("requested_count")
        if requested_count not in (None, "", [], {}):
            execution_known["requested_count"] = requested_count
        fields = source_contract.get("requested_output_fields") if isinstance(source_contract.get("requested_output_fields"), list) else []
        if fields:
            execution_known["requested_output_fields"] = fields
        for container_key in ("execution_known", "parameters", "known_parameters"):
            value = raw.get(container_key) if isinstance(raw.get(container_key), dict) else {}
            for key, item in value.items():
                normalized = str(key or "").strip().lower().replace(" ", "_").replace("-", "_")
                if normalized in {"title", "summary", "description", "objective", "instruction", "original_input", "prompt"}:
                    continue
                if item not in (None, "", [], {}):
                    execution_known[str(key)] = item
        semantic_known = raw.get("semantic_known") if isinstance(raw.get("semantic_known"), dict) else {"verified_facts": [], "source_materials": [], "unknowns": []}
        if source_contract.get("requires_source_material") is True and not semantic_known.get("source_materials") and not semantic_known.get("verified_facts"):
            semantic_known = {**semantic_known, "unknowns": sorted(set((semantic_known.get("unknowns") or []) + ["external_source_material"]))}
        task_metadata = {
            "instruction": instruction,
            "step_name": str(raw.get("display_name") or raw.get("participant_display_name") or raw.get("name") or ""),
        }
        return {"execution_known": execution_known, "semantic_known": semantic_known, "task_metadata": task_metadata}

    def _execution_contract(self, raw: dict[str, Any], prompt_profile: dict[str, Any]) -> dict[str, Any]:
        existing = raw.get("execution_contract") if isinstance(raw.get("execution_contract"), dict) else {}
        profile = raw.get("capability_profile") if isinstance(raw.get("capability_profile"), dict) else {}
        owner = str(existing.get("execution_owner") or raw.get("execution_owner") or profile.get("execution_owner") or "ai_core").strip()
        return {
            **existing,
            "execution_owner": owner,
            "execution_method": str(existing.get("execution_method") or raw.get("execution_method") or ("web_search" if (raw.get("source_contract") or {}).get("requires_source_material") is True else "locked_runtime_plan")),
            "prompt_profile": prompt_profile.get("prompt_profile"),
            "capability_id": str(existing.get("capability_id") or profile.get("tool_id") or profile.get("capability") or "").strip(),
            "runtime_prompt_guessing": False,
        }

    def _source_contract(self, raw: dict[str, Any], instruction: str = "") -> dict[str, Any]:
        existing = raw.get("source_contract") if isinstance(raw.get("source_contract"), dict) else {}
        fields = existing.get("requested_output_fields") if isinstance(existing.get("requested_output_fields"), list) else self._requested_fields(instruction)
        cardinality = existing.get("output_cardinality") if isinstance(existing.get("output_cardinality"), dict) else {}
        if not cardinality or cardinality.get("mode") == "unspecified":
            cardinality = self._output_cardinality(instruction)
        requires_source_material = existing.get("requires_source_material")
        if requires_source_material is None:
            requires_source_material = self._requires_source_material(fields)
        return {
            **existing,
            "material_order": existing.get("material_order") or ["url_page", "visible_text", "text_excerpt", "search_cards", "blocked"],
            "direct_relevance_claim_without_material": False,
            "requires_source_material": bool(requires_source_material),
            "requested_output_fields": fields,
            "output_cardinality": cardinality,
            "single_step_multi_item_output": bool(cardinality.get("requested_count")),
        }

    def _requested_fields(self, instruction: str) -> list[str]:
        fields: list[str] = []
        for raw in str(instruction or "").splitlines():
            line = raw.strip()
            if not line.startswith(("-", "*")):
                continue
            field = line.lstrip("-* ").strip().strip(":：")
            if field:
                fields.append(field.casefold())
        return fields

    def _requires_source_material(self, fields: list[str]) -> bool:
        normalized = {re.sub(r"[^a-z0-9]+", "_", str(item).casefold()).strip("_") for item in fields}
        provenance_fields = {
            "source", "sources", "reference", "references", "citation", "citations",
            "url", "link", "links", "published_at", "publication_time", "time", "date",
        }
        return bool(normalized & provenance_fields)

    def _output_cardinality(self, instruction: str) -> dict[str, Any]:
        text = str(instruction or "")
        lower = text.casefold()
        word_numbers = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }
        patterns = [
            r"(?<![A-Za-z0-9_])(?P<n>\d{1,2})\s+(?:of\s+the\s+)?(?:latest|recent|newest|top|first|last)?\s*[^\n.。:：]{0,80}(?:\n|$|[.。:：])",
            r"(?<![A-Za-z0-9_])(?P<n>one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:of\s+the\s+)?(?:latest|recent|newest|top|first|last)?\s*[^\n.。:：]{0,80}(?:\n|$|[.。:：])",
        ]
        for pattern in patterns:
            match = re.search(pattern, lower, flags=re.I)
            if not match:
                continue
            token = str(match.group("n") or "").casefold()
            count = int(token) if token.isdigit() else int(word_numbers.get(token, 0) or 0)
            if count > 0:
                return {
                    "mode": "exact_requested_count",
                    "requested_count": count,
                    "source": "structural_instruction",
                    "matched_text": match.group(0).strip(),
                    "compile_policy": "preserve_as_single_step_output_requirement",
                }
        return {"mode": "unspecified"}

    def _presentation_contract(self, raw: dict[str, Any]) -> dict[str, Any]:
        existing = raw.get("presentation_contract") if isinstance(raw.get("presentation_contract"), dict) else {}
        outputs = existing.get("exportable_outputs") if isinstance(existing.get("exportable_outputs"), list) else ["presentation.final_answer"]
        return {**existing, "exportable_outputs": outputs, "exclude_failure_messages": True}

    def _binding_contract(self, raw: dict[str, Any]) -> dict[str, Any]:
        bindings = raw.get("workflow_bindings") if isinstance(raw.get("workflow_bindings"), list) else []
        return {"bindings": [b for b in bindings if isinstance(b, dict)], "template_parsing_enabled": False}

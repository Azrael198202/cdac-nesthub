from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .prompt_compiler import PromptProfileCompiler


@dataclass
class StepCompiler:
    prompt_compiler: PromptProfileCompiler = field(default_factory=PromptProfileCompiler)

    def compile_steps(self, task_graph: dict[str, Any]) -> list[dict[str, Any]]:
        raw_steps = task_graph.get("tasks") if isinstance(task_graph.get("tasks"), list) else []
        compiled: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_steps, start=1):
            if not isinstance(raw, dict):
                continue
            step_id = str(raw.get("source_step_id") or raw.get("step_id") or f"step_{index:03d}").strip()
            instruction = str(raw.get("source_instruction_fragment") or raw.get("instruction") or raw.get("execution_objective") or raw.get("objective") or "").strip()
            prompt_profile = self.prompt_compiler.compile_for_step(raw)
            execution_contract = self._execution_contract(raw, prompt_profile)
            source_contract = self._source_contract(raw)
            presentation_contract = self._presentation_contract(raw)
            binding_contract = self._binding_contract(raw)
            compiled.append({
                "step_id": step_id,
                "step_index": index,
                "step_name": str(raw.get("display_name") or raw.get("participant_display_name") or raw.get("name") or step_id),
                "participant_id": str(raw.get("participant_id") or raw.get("id") or step_id),
                "instruction": instruction,
                "depends_on": [str(x) for x in (raw.get("depends_on") or []) if str(x).strip()],
                "prompt_profile": prompt_profile,
                "execution_contract": execution_contract,
                "source_contract": source_contract,
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
                },
            })
        return compiled

    def _execution_contract(self, raw: dict[str, Any], prompt_profile: dict[str, Any]) -> dict[str, Any]:
        existing = raw.get("execution_contract") if isinstance(raw.get("execution_contract"), dict) else {}
        profile = raw.get("capability_profile") if isinstance(raw.get("capability_profile"), dict) else {}
        owner = str(existing.get("execution_owner") or raw.get("execution_owner") or profile.get("execution_owner") or "ai_core").strip()
        return {
            **existing,
            "execution_owner": owner,
            "execution_method": str(existing.get("execution_method") or raw.get("execution_method") or "locked_runtime_plan"),
            "prompt_profile": prompt_profile.get("prompt_profile"),
            "capability_id": str(existing.get("capability_id") or profile.get("tool_id") or profile.get("capability") or "").strip(),
            "runtime_prompt_guessing": False,
        }

    def _source_contract(self, raw: dict[str, Any]) -> dict[str, Any]:
        existing = raw.get("source_contract") if isinstance(raw.get("source_contract"), dict) else {}
        return {
            **existing,
            "material_order": existing.get("material_order") or ["url_page", "visible_text", "text_excerpt", "search_cards", "blocked"],
            "direct_relevance_claim_without_material": False,
        }

    def _presentation_contract(self, raw: dict[str, Any]) -> dict[str, Any]:
        existing = raw.get("presentation_contract") if isinstance(raw.get("presentation_contract"), dict) else {}
        outputs = existing.get("exportable_outputs") if isinstance(existing.get("exportable_outputs"), list) else ["presentation.final_answer"]
        return {**existing, "exportable_outputs": outputs, "exclude_failure_messages": True}

    def _binding_contract(self, raw: dict[str, Any]) -> dict[str, Any]:
        bindings = raw.get("workflow_bindings") if isinstance(raw.get("workflow_bindings"), list) else []
        return {"bindings": [b for b in bindings if isinstance(b, dict)], "template_parsing_enabled": False}

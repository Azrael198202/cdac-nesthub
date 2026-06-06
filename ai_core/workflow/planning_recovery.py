from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class PlanningRecoveryService:
    """Generic recovery when the planner produced no executable steps.

    This is not a domain fallback. It does not infer any business-specific
    action. It only preserves the original request and creates a capability-
    discovery step when the workflow has enough user input to continue into the
    runtime discovery/generation pipeline.
    """

    def recover_if_empty(self, *, workflow_plan: dict[str, Any], user_input: str, previous_results: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(workflow_plan, dict):
            workflow_plan = {}
        existing = workflow_plan.get("planned_steps")
        if isinstance(existing, list) and existing:
            return workflow_plan
        if not str(user_input or "").strip():
            return workflow_plan

        recovered = dict(workflow_plan)
        recovered["planned_steps"] = [self._generic_generation_step(user_input=user_input, previous_results=previous_results or {})]
        recovered.setdefault("required_capabilities", ["generic_content_generation"])
        recovered.setdefault("blocking_missing_information", [])
        recovered["recovery"] = {
            "status": "planner_empty_recovered",
            "reason": "Planner returned no executable steps. Created a strict generic content-generation step from the original request.",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return recovered

    def _generic_generation_step(self, *, user_input: str, previous_results: dict[str, Any]) -> dict[str, Any]:
        intent = previous_results.get("intent_recognition") if isinstance(previous_results.get("intent_recognition"), dict) else {}
        parsed = previous_results.get("input_parsing") if isinstance(previous_results.get("input_parsing"), dict) else {}
        return {
            "task_id": "content_generation_1",
            "step_id": "content_generation_1",
            "task_type": "content_generation",
            "action": "generate_content_from_locked_parameters",
            "objective": "Generate the requested content from the locked user parameters without external evidence retrieval.",
            "parameters": {
                "known": {
                    "original_user_input": user_input,
                    "parsed_input": parsed,
                    "recognized_intent": intent,
                },
                "optional": {
                    "preserve_user_constraints_and_modifiers": True,
                    "use_external_evidence_when_current_capability_is_insufficient": False,
                },
                "missing_required": {},
            },
            "required_capability": "generic_content_generation",
            "execution_method": "content_generation",
            "execution_method_policy": {
                "preferred_methods": ["content_generation"],
                "disabled_methods": ["web_search", "api_call"],
                "fallback_allowed": False
            },
            "execution_strategy": ["content_generation"],
            "source_policy": {"allow_external": False, "requires_live_evidence": False},
            "execution_ready": True,
            "depends_on": [],
            "requires_human_confirmation": False,
        }

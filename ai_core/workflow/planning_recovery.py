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
        recovered["planned_steps"] = [self._generic_discovery_step(user_input=user_input, previous_results=previous_results or {})]
        recovered.setdefault("required_capabilities", ["runtime_external_capability_discovery"])
        recovered.setdefault("blocking_missing_information", [])
        recovered["recovery"] = {
            "status": "planner_empty_recovered",
            "reason": "Planner returned no executable steps. Created a generic runtime capability-discovery step from the original request.",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return recovered

    def _generic_discovery_step(self, *, user_input: str, previous_results: dict[str, Any]) -> dict[str, Any]:
        intent = previous_results.get("intent_recognition") if isinstance(previous_results.get("intent_recognition"), dict) else {}
        parsed = previous_results.get("input_parsing") if isinstance(previous_results.get("input_parsing"), dict) else {}
        return {
            "task_id": "runtime_capability_discovery_1",
            "step_id": "runtime_capability_discovery_1",
            "task_type": "runtime_capability_discovery",
            "action": "discover_generate_verify_and_execute_runtime_capability",
            "objective": "Use the original user request and runtime evidence to discover or generate an executable read-only capability, verify it, execute it, and return a grounded result.",
            "parameters": {
                "known": {
                    "original_user_input": user_input,
                    "parsed_input": parsed,
                    "recognized_intent": intent,
                },
                "optional": {
                    "preserve_user_constraints_and_modifiers": True,
                    "use_external_evidence_when_current_capability_is_insufficient": True,
                },
                "missing_required": {},
            },
            "required_capability": "runtime_external_capability_discovery",
            "execution_ready": True,
            "depends_on": [],
            "requires_human_confirmation": False,
        }

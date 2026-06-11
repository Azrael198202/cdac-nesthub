from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionPlanCompiler:
    def compile(self, steps: list[dict[str, Any]], bindings: list[dict[str, Any]], task_graph: dict[str, Any]) -> dict[str, Any]:
        return {
            "plan_id": str(task_graph.get("graph_id") or task_graph.get("task_name") or "compiled_plan"),
            "execution_mode": "execute_compiled_task",
            "context_isolation": {
                "task_context_inheritance": True,
                "sibling_step_context_inheritance": False,
                "required_runtime_fields": ["task_session_id", "step_execution_id"],
            },
            "steps": [
                {
                    "step_id": step.get("step_id"),
                    "execution_owner": (step.get("execution_contract") or {}).get("execution_owner"),
                    "execution_method": (step.get("execution_contract") or {}).get("execution_method"),
                    "prompt_profile": (step.get("prompt_profile") or {}).get("prompt_profile"),
                    "depends_on": step.get("depends_on") or [],
                    "bindings_in": [b.get("binding_id") for b in bindings if b.get("target_step") == step.get("step_id")],
                    "bindings_out": [b.get("binding_id") for b in bindings if b.get("source_step") == step.get("step_id")],
                }
                for step in steps
            ],
            "binding_resolution": {
                "resolver": "ResolveBinding",
                "template_parsing_enabled": False,
            },
            "presentation_bridge": {
                "enabled": True,
                "exclude_failure_messages_from_exportable_outputs": True,
            },
        }

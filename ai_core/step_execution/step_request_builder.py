from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class StepRequestBuilder:
    def build(self, *, compiled_step: dict[str, Any], task_session_id: str, task_context: dict[str, Any] | None = None, resolved_bindings: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "task_session_id": task_session_id,
            "step_execution_id": f"step_execution_{uuid4().hex}",
            "step_id": str(compiled_step.get("step_id") or ""),
            "instruction": str(compiled_step.get("instruction") or ""),
            "prompt_profile": (compiled_step.get("prompt_profile") or {}).get("prompt_profile") if isinstance(compiled_step.get("prompt_profile"), dict) else "",
            "execution_contract": compiled_step.get("execution_contract") if isinstance(compiled_step.get("execution_contract"), dict) else {},
            "source_contract": compiled_step.get("source_contract") if isinstance(compiled_step.get("source_contract"), dict) else {},
            "presentation_contract": compiled_step.get("presentation_contract") if isinstance(compiled_step.get("presentation_contract"), dict) else {},
            "task_context": task_context if isinstance(task_context, dict) else {},
            "resolved_bindings": resolved_bindings if isinstance(resolved_bindings, dict) else {},
            "context_isolation": {
                "task_context_inheritance": True,
                "sibling_step_context_inheritance": False,
            },
        }

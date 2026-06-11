from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from .step_request_builder import StepRequestBuilder
from .step_result_builder import StepResultBuilder


@dataclass
class StepExecutionBridge:
    """Boundary from compiled step assets into ai_core execution.

    The bridge does not choose capabilities or prompts. It only transfers the
    locked compiled step contract into a runtime request and wraps the result.
    """

    request_builder: StepRequestBuilder = field(default_factory=StepRequestBuilder)
    result_builder: StepResultBuilder = field(default_factory=StepResultBuilder)

    async def execute(self, *, compiled_step: dict[str, Any], task_session_id: str, executor: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]], task_context: dict[str, Any] | None = None, resolved_bindings: dict[str, Any] | None = None) -> dict[str, Any]:
        request = self.request_builder.build(compiled_step=compiled_step, task_session_id=task_session_id, task_context=task_context, resolved_bindings=resolved_bindings)
        raw = await executor(request)
        return self.result_builder.build(step_request=request, raw_result=raw)

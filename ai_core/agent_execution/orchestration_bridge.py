from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from ai_core.orchestration.workflow_runtime import WorkflowRuntime


@dataclass(slots=True)
class CoreOrchestrationResult:
    run_id: str
    status: str
    final_text: str
    results: dict[str, Any]
    events_summary: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "final_text": self.final_text,
            "results": self.results,
            "events_summary": self.events_summary,
        }


class AICoreOrchestrationBridge:
    """Executes generated-agent work through the main orchestration runtime.

    The bridge is intentionally neutral: it receives a runtime-generated request
    string and routes it through the same input/intent/context/planning/execution
    pipeline used by the primary chat endpoint. It does not know business
    domains, tool names, or agent roles.
    """

    ORIGIN = "ai_core"

    def __init__(self) -> None:
        self.runtime = WorkflowRuntime()

    async def execute(self, request_text: str, *, local_model: str | None = None) -> dict[str, Any]:
        run_id, state = await self.runtime.prepare(request_text, local_model=local_model)
        await self.runtime.run_prepared(state)
        results = state.get("results", {}) if isinstance(state.get("results"), dict) else {}
        output_result = results.get("output", {}) if isinstance(results.get("output"), dict) else {}
        final_text = (
            output_result.get("final_answer")
            or output_result.get("message")
            or self._fallback_text(results)
            or ""
        )
        status = str(output_result.get("status") or state.get("final_status") or "completed")
        return CoreOrchestrationResult(
            run_id=run_id,
            status=status,
            final_text=str(final_text),
            results=results,
            events_summary=self._summarize_results(results),
        ).to_dict()

    def _fallback_text(self, results: dict[str, Any]) -> str:
        for key in ("execution", "workflow_planning", "intent_recognition"):
            value = results.get(key)
            if isinstance(value, dict):
                for field in ("final_answer", "message", "answer", "summary"):
                    if value.get(field):
                        return str(value.get(field))
        return ""

    def _summarize_results(self, results: dict[str, Any]) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for key, value in results.items():
            if isinstance(value, dict):
                status = value.get("status") or value.get("execution_status") or "completed"
                message = value.get("message") or value.get("final_answer") or value.get("answer") or ""
            else:
                status = "completed"
                message = str(value)
            summary.append({"origin": self.ORIGIN, "node_id": str(key), "status": str(status), "message": str(message)[:240]})
        return summary


def build_core_execution_request(*, task: Any, agent: Any, inputs: dict[str, Any] | None = None) -> str:
    """Build a neutral request for the primary runtime from generated metadata."""
    metadata = getattr(agent, "metadata", {}) or {}
    instruction = str(metadata.get("execution_instruction") or metadata.get("user_instruction") or "").strip()
    objective = str(getattr(task, "objective", "") or "").strip()
    parts = [part for part in [instruction, objective] if part]
    if inputs:
        parts.append("Available upstream material:\n" + "\n".join(str(v.get("result_text") if isinstance(v, dict) else v) for v in inputs.values()))
    return "\n".join(dict.fromkeys(parts)) or f"generated runtime request {uuid4().hex[:8]}"

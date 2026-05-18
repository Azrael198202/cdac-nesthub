from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from typing import Any
from uuid import uuid4

from ai_core.orchestration.workflow_runtime import WorkflowRuntime


@dataclass
class AgentExecutionRequest:
    participant_id: str
    participant_name: str
    participant_instruction: str
    task_name: str
    task_instruction: str
    community_id: str
    shared_context: dict[str, Any]


@dataclass
class AgentExecutionResult:
    participant_id: str
    participant_name: str
    core_run_id: str
    status: str
    final_answer: str
    workflow_results: dict[str, Any]
    origin: str = "ai_core"
    pending_action: dict[str, Any] | None = None
    missing_inputs: list[dict[str, Any]] | None = None


class PrimaryBrainDelegationClient:
    """Delegates role work to the primary runtime.

    The auxiliary layer calls this client; the primary runtime performs parsing,
    planning, tool selection, execution, verification, and synthesis.
    """

    def __init__(self, runtime: WorkflowRuntime | None = None) -> None:
        self.runtime = runtime or WorkflowRuntime()

    async def execute_agent_request(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        message = self._build_agent_message(request)
        core_run_id, state = await self.runtime.prepare(message)
        state.setdefault("runtime_options", {})["delegation_mode"] = True
        state.setdefault("runtime_options", {})["auto_approve_reviews"] = True
        await self.runtime.run_prepared(state)
        final_answer = self._extract_final_answer(state)
        status = self._extract_status(state)
        pending_action = state.get("pending_action") if isinstance(state, dict) else None
        return AgentExecutionResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id=core_run_id,
            status=status,
            final_answer=final_answer,
            workflow_results=state.get("results", {}),
            pending_action=pending_action if isinstance(pending_action, dict) else None,
            missing_inputs=self._extract_missing_inputs(state),
        )

    async def synthesize_delegated_results(
        self,
        *,
        task_name: str,
        task_instruction: str,
        agent_results: list[AgentExecutionResult],
        shared_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message = self._build_synthesis_message(task_name, task_instruction, agent_results, shared_context or {})
        core_run_id, state = await self.runtime.prepare(message)
        state.setdefault("runtime_options", {})["delegation_mode"] = True
        state.setdefault("runtime_options", {})["auto_approve_reviews"] = True
        await self.runtime.run_prepared(state)
        return {
            "origin": "ai_core",
            "core_run_id": core_run_id,
            "status": self._extract_status(state),
            "final_answer": self._extract_final_answer(state),
            "workflow_results": state.get("results", {}),
        }

    def _build_agent_message(self, request: AgentExecutionRequest) -> str:
        return (
            f"{request.participant_instruction}\n\n"
            "Task context:\n"
            f"Task name: {request.task_name}\n"
            f"Task instruction: {request.task_instruction}\n"
            "Return only the participant result needed for this task."
        )

    def _build_synthesis_message(
        self,
        task_name: str,
        task_instruction: str,
        agent_results: list[AgentExecutionResult],
        shared_context: dict[str, Any],
    ) -> str:
        result_blocks = []
        for result in agent_results:
            result_blocks.append(
                f"Participant: {result.participant_name}\n"
                f"Status: {result.status}\n"
                f"Result: {result.final_answer}"
            )
        return (
            "Synthesize the delegated participant results into the final answer for the user.\n"
            f"Task name: {task_name}\n"
            f"Task instruction: {task_instruction}\n"
            "Participant results:\n"
            + "\n---\n".join(result_blocks)
            + "\nReturn a concise final answer."
        )

    def _extract_final_answer(self, state: dict[str, Any]) -> str:
        results = state.get("results", {}) if isinstance(state, dict) else {}
        output = results.get("output") if isinstance(results, dict) else None
        if isinstance(output, dict):
            for key in ["final_answer", "message", "answer", "result"]:
                value = output.get(key)
                if value:
                    return str(value)
        for key in ["final_answer", "message", "answer", "result"]:
            value = state.get(key) if isinstance(state, dict) else None
            if value:
                return str(value)
        pending = state.get("pending_action") if isinstance(state, dict) else None
        if pending:
            return "The primary runtime paused before producing a user-facing final answer."
        if isinstance(results, dict) and results:
            return str(results)
        return "The primary runtime completed without a user-facing final answer."

    def _extract_status(self, state: dict[str, Any]) -> str:
        pending = state.get("pending_action") if isinstance(state, dict) else None
        if isinstance(pending, dict):
            kind = str(pending.get("kind") or "pending")
            if kind in {"secret_input", "optional_credential_choice"}:
                return "requires_key"
            if kind == "human_information_required":
                return "requires_input"
            return "paused"
        results = state.get("results", {}) if isinstance(state, dict) else {}
        output = results.get("output") if isinstance(results, dict) else None
        if isinstance(output, dict):
            return str(output.get("status") or output.get("execution_status") or "completed")
        return "completed"

    def _extract_missing_inputs(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        pending = state.get("pending_action") if isinstance(state, dict) else None
        if not isinstance(pending, dict):
            return []
        kind = str(pending.get("kind") or "")
        if kind == "secret_input":
            return [{
                "kind": "secret_input",
                "field": str(pending.get("secret_key") or "runtime_access_key"),
                "message": "A runtime access key is required to continue this delegated execution.",
            }]
        if kind == "optional_credential_choice":
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            return [{
                "kind": "optional_credential_choice",
                "field": str(request.get("secret_key") or request.get("provider") or "runtime_access_key"),
                "message": str(request.get("message") or pending.get("message") or "A runtime access key can improve this execution."),
            }]
        if kind == "human_information_required":
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            fields = request.get("fields") or request.get("missing_fields") or []
            if isinstance(fields, list):
                return [{"kind": "human_information_required", "field": str(f), "message": str(request.get("message") or "Additional information is required.")} for f in fields]
        return []

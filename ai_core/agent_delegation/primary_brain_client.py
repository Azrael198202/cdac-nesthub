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
        await self.runtime.run_prepared(state)
        final_answer = self._extract_final_answer(state)
        status = self._extract_status(state)
        return AgentExecutionResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id=core_run_id,
            status=status,
            final_answer=final_answer,
            workflow_results=state.get("results", {}),
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
            "Execute the delegated participant work using the primary runtime.\n"
            f"Participant name: {request.participant_name}\n"
            f"Participant instruction: {request.participant_instruction}\n"
            f"Task name: {request.task_name}\n"
            f"Task instruction: {request.task_instruction}\n"
            "Return only the participant result needed for the task."
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
        if isinstance(results, dict) and results:
            return str(results)
        return "The primary runtime completed without a user-facing final answer."

    def _extract_status(self, state: dict[str, Any]) -> str:
        results = state.get("results", {}) if isinstance(state, dict) else {}
        output = results.get("output") if isinstance(results, dict) else None
        if isinstance(output, dict):
            return str(output.get("status") or output.get("execution_status") or "completed")
        return "completed"

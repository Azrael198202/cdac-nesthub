from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
from typing import Any

from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime
from auxiliary_brain.storage import JsonStore
from ai_core.agent_delegation import AgentExecutionResult


class DummyPrimaryClient:
    async def synthesize_delegated_results(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "completed", "final_answer": "synthesized"}


async def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        runtime = AgentDelegationRuntime(store=JsonStore(Path(td) / "runtime"), primary_client=DummyPrimaryClient())
        called: list[dict[str, Any]] = []

        async def fake_execute_registered_tool_capability(*, participant, task_name, completed_results=None, dependency_plan=None):
            called.append({
                "participant_id": participant.get("participant_id"),
                "task_name": task_name,
                "completed_count": len(completed_results or []),
                "capability_profile": participant.get("capability_profile"),
            })
            return AgentExecutionResult(
                participant_id=str(participant.get("participant_id")),
                participant_name=str(participant.get("display_name") or participant.get("name")),
                core_run_id="registered_tool_result_test",
                status="completed",
                final_answer="registered tool executed",
                workflow_results={"status": "completed", "capability_type": "runtime_registered_tool", "tool_id": "generic_tool"},
                origin="auxiliary_brain",
            )

        runtime._execute_registered_tool_capability = fake_execute_registered_tool_capability  # type: ignore[method-assign]

        async def fake_resume_agent_request_with_progress(payload, progress_callback=None, provided_inputs=None):
            return AgentExecutionResult(
                participant_id="agent_a",
                participant_name="Agent A",
                core_run_id="a_resumed",
                status="completed",
                final_answer="A out",
                workflow_results={},
                origin="auxiliary_brain",
            )

        async def fake_execute_intermediate_step_with_progress(request, progress_callback=None):
            return AgentExecutionResult(
                participant_id="step_b",
                participant_name="Extract",
                core_run_id="b",
                status="completed",
                final_answer="B out",
                workflow_results={"dataflow_step": {"verified_result_material": {"type": "text", "text": "B out"}}},
                origin="auxiliary_brain",
            )

        runtime._resume_agent_request_with_progress = fake_resume_agent_request_with_progress  # type: ignore[method-assign]
        runtime._execute_intermediate_step_with_progress = fake_execute_intermediate_step_with_progress  # type: ignore[method-assign]

        task_graph = {
            "task_name": "GenericTask",
            "instruction": "Step 1 agent A. Step 2 extract. Step 3 agent C.",
            "selected_participant_ids": ["agent_a", "step_b", "agent_c"],
            "tasks": [
                {"participant_id": "agent_a"},
                {"participant_id": "step_b", "depends_on": ["agent_a"]},
                {"participant_id": "agent_c", "depends_on": ["step_b"]},
            ],
        }
        participants = [
            {"participant_id": "agent_a", "display_name": "Agent A", "execution_objective": "A"},
            {"participant_id": "step_b", "display_name": "Extract", "workflow_step_type": "semantic_intermediate_step", "depends_on": ["agent_a"]},
            {
                "participant_id": "agent_c",
                "display_name": "Agent C",
                "execution_objective": "C",
                "depends_on": ["step_b"],
                "capability_profile": {
                    "capability_type": "runtime_registered_tool",
                    "tool_id": "generic_tool",
                    "tool_summary": {"input_schema": {"type": "object", "properties": {}, "required": []}},
                },
                "execution_policy": "runtime_registered_tool",
            },
        ]
        run_payload = {
            "run_id": "delegation_run_test",
            "task_name": "GenericTask",
            "status": "resuming",
            "agent_results": [
                {"participant_id": "agent_a", "participant_name": "Agent A", "core_run_id": "a", "status": "paused", "final_answer": "", "workflow_results": {}, "origin": "auxiliary_brain", "pending_action": {"kind": "dummy"}},
            ],
        }
        result = await runtime.resume_task(run_payload, task_graph, participants, provided_inputs={})
        assert called, "resume_task must execute the remaining runtime_registered_tool participant directly"
        assert called[0]["participant_id"] == "agent_c"
        assert called[0]["capability_profile"]["tool_id"] == "generic_tool"
        out = result.get("agent_results") or []
        assert any((r.get("workflow_results") or {}).get("capability_type") == "runtime_registered_tool" for r in out), out
        print("OK resume path executes registered-tool participant directly")


if __name__ == "__main__":
    asyncio.run(main())

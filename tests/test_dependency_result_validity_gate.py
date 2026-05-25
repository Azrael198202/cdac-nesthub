import pytest

from ai_core.agent_delegation import AgentExecutionResult
from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime


class FakePrimaryClient:
    def __init__(self):
        self.agent_calls = []
        self.step_calls = []

    async def execute_agent_request(self, request, progress_callback=None):
        self.agent_calls.append(request.participant_id)
        return AgentExecutionResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id="run-a",
            status="completed",
            final_answer="The workflow is blocked and did not execute a tool yet. Please review the blocked step details.",
            workflow_results={},
        )

    async def execute_intermediate_step(self, request, progress_callback=None):
        self.step_calls.append(request.participant_id)
        return AgentExecutionResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id="run-b",
            status="completed",
            final_answer="should not run",
            workflow_results={},
        )

    async def synthesize_delegated_results(self, **kwargs):
        return {"status": "partial_failed", "final_answer": "done", "workflow_results": {}}


@pytest.mark.asyncio
async def test_invalid_completed_upstream_blocks_downstream_execution():
    fake = FakePrimaryClient()
    runtime = AgentDelegationRuntime(primary_client=fake)
    participants = [
        {"participant_id": "p1", "display_name": "First", "instruction": "run first"},
        {"participant_id": "p2", "display_name": "Second", "workflow_step_type": "semantic_intermediate_step", "instruction": "use first", "depends_on": ["p1"]},
        {"participant_id": "p3", "display_name": "Third", "workflow_step_type": "semantic_intermediate_step", "instruction": "use second", "depends_on": ["p2"]},
    ]
    task_graph = {
        "graph_id": "g1",
        "task_name": "Generic graph",
        "instruction": "Execute a dependent graph.",
        "tasks": [
            {"participant_id": "p2", "depends_on": ["p1"], "step_type": "semantic_intermediate_step"},
            {"participant_id": "p3", "depends_on": ["p2"], "step_type": "semantic_intermediate_step"},
        ],
    }

    result = await runtime._execute_task_with_selected(task_graph, participants)
    statuses = {item["participant_id"]: item["status"] for item in result["agent_results"]}

    assert fake.agent_calls == ["p1"]
    assert fake.step_calls == []
    assert statuses["p1"] == "failed"
    assert statuses["p2"] == "skipped"
    assert statuses["p3"] == "skipped"
    assert result["agent_results"][1]["workflow_results"]["dependency_gate"]["blockers"]


@pytest.mark.asyncio
async def test_step_reference_dependencies_block_generated_downstream_execution():
    fake = FakePrimaryClient()
    runtime = AgentDelegationRuntime(primary_client=fake)
    participants = [
        {"participant_id": "p1", "display_name": "First", "instruction": "run first"},
        {"participant_id": "p2", "display_name": "Second", "workflow_step_type": "semantic_intermediate_step", "instruction": "use first"},
    ]
    task_graph = {
        "graph_id": "g_step_refs",
        "task_name": "Generic graph",
        "instruction": "Execute a dependent graph.",
        "tasks": [
            {"task_id": "task_1", "source_step_id": "step1", "participant_id": "p1", "step_type": "participant_execution"},
            {"task_id": "task_2", "source_step_id": "step2", "participant_id": "p2", "depends_on": ["step1"], "step_type": "semantic_intermediate_step"},
        ],
    }

    result = await runtime._execute_task_with_selected(task_graph, participants)
    statuses = {item["participant_id"]: item["status"] for item in result["agent_results"]}
    assert fake.step_calls == []
    assert statuses["p1"] == "failed"
    assert statuses["p2"] == "skipped"

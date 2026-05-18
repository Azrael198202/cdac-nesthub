import asyncio
from dataclasses import dataclass

from auxiliary_brain.delegation import AgentDelegationRuntime
from auxiliary_brain.storage import JsonStore


@dataclass
class FakeResult:
    participant_id: str
    participant_name: str
    core_run_id: str
    status: str
    final_answer: str
    workflow_results: dict
    origin: str = "ai_core"


class FakePrimaryClient:
    def __init__(self):
        self.requests = []
        self.synthesis_requests = []

    async def execute_agent_request(self, request):
        self.requests.append(request)
        return FakeResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id="core_unit",
            status="completed",
            final_answer=f"done:{request.participant_name}",
            workflow_results={"output": {"status": "completed"}},
        )

    async def synthesize_delegated_results(self, *, task_name, task_instruction, agent_results, shared_context=None):
        self.synthesis_requests.append((task_name, task_instruction, agent_results, shared_context))
        return {"origin": "ai_core", "core_run_id": "core_final", "status": "completed", "final_answer": "final"}


def test_delegation_runtime_calls_primary_for_each_participant(tmp_path):
    store = JsonStore(tmp_path / "runtime")
    primary = FakePrimaryClient()
    runtime = AgentDelegationRuntime(store=store, primary_client=primary)
    task_graph = {"graph_id": "g1", "task_name": "unit_task", "instruction": "combine Alpha and Beta", "community_id": "c1"}
    participants = [
        {"participant_id": "p1", "name": "Alpha", "instruction": "do alpha"},
        {"participant_id": "p2", "name": "Beta", "instruction": "do beta"},
    ]
    result = asyncio.run(runtime.execute_task(task_graph, participants))
    assert result["status"] == "completed"
    assert len(primary.requests) == 2
    assert primary.synthesis_requests
    assert result["synthesis"]["final_answer"] == "final"

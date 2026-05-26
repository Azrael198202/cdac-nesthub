import asyncio
from types import SimpleNamespace

from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime
from ai_core.agent_delegation import AgentExecutionResult


def participant(pid, name, depends=None):
    return {
        "participant_id": pid,
        "agent_name": name,
        "name": name,
        "execution_objective": name,
        "depends_on": depends or [],
        "parameter_contract": {"parameters": []},
    }


def test_selected_participant_order_follows_task_graph_order():
    rt = AgentDelegationRuntime()
    task = {"selected_participant_ids": ["a", "b", "c"]}
    registry_order = [participant("c", "C"), participant("a", "A"), participant("b", "B")]
    selected = rt._select_participants(task, registry_order)
    assert [p["participant_id"] for p in selected] == ["a", "b", "c"]


def test_dependency_guard_rejects_placeholder_completed_result():
    rt = AgentDelegationRuntime()
    downstream = participant("dst", "Downstream")
    plan = {"participants": {"dst": {"depends_on": ["src"]}}}
    bad = AgentExecutionResult(
        participant_id="src",
        participant_name="Source",
        core_run_id="r",
        status="completed",
        final_answer="The workflow is blocked and did not execute a tool yet.",
        workflow_results={},
    )
    assert rt._dependencies_satisfied(downstream, [bad], plan) is False


def test_dependency_guard_accepts_verified_completed_result():
    rt = AgentDelegationRuntime()
    downstream = participant("dst", "Downstream")
    plan = {"participants": {"dst": {"depends_on": ["src"]}}}
    good = AgentExecutionResult(
        participant_id="src",
        participant_name="Source",
        core_run_id="r",
        status="completed",
        final_answer="Verified result value 12345",
        workflow_results={},
    )
    assert rt._dependencies_satisfied(downstream, [good], plan) is True


def test_peer_results_include_only_verified_dependency_material():
    rt = AgentDelegationRuntime()
    downstream = participant("dst", "Downstream")
    plan = {"participants": {"dst": {"depends_on": ["src"]}}}
    bad = AgentExecutionResult("src", "Source", "r1", "completed", "Agent actions and substeps planned with locked fixed execution options.", {})
    good = AgentExecutionResult("src", "Source", "r2", "completed", "Actual result material 123", {})
    peer = rt._peer_results_for_participant(downstream, [bad, good], plan)
    assert len(peer) == 1
    assert peer[0]["final_answer_summary"] == "Actual result material 123"

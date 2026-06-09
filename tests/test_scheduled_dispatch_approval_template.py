from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime
from ai_core.agent_delegation import AgentExecutionResult


def test_auto_approved_tool_does_not_block_agent_approval_parameter():
    runtime = AgentDelegationRuntime()
    runtime.registered_tool_service.approval_policy_store.set_tool_policy(
        tool_id="tool_for_test", profile_id="default", mode="never"
    )
    participant = {
        "participant_id": "participant_for_test",
        "agent_name": "Runtime participant",
        "capability_profile": {"tool_id": "tool_for_test"},
        "parameter_contract": {
            "parameters": [
                {
                    "name": "approval_confirmed",
                    "required": True,
                    "blocking": True,
                    "execution_required": True,
                }
            ]
        },
        "runtime_parameters": {},
    }

    assert runtime._collect_missing_agent_parameter_fields([participant], dependency_plan={}) == []


def test_original_step_alias_survives_payload_only_scheduled_dispatch():
    runtime = AgentDelegationRuntime()
    completed = [
        AgentExecutionResult(
            participant_id="participant_step_two",
            participant_name="Time participant",
            core_run_id="run1",
            status="completed",
            final_answer="2026-06-09 17:20",
            workflow_results={"final_answer": "2026-06-09 17:20"},
            origin="test",
        )
    ]
    consumer = {"participant_id": "participant_step_three", "agent_name": "Consumer"}
    task_graph = {
        "tasks": [
            {"participant_id": "controller", "source_step_id": "Step 1"},
            {"participant_id": "participant_step_two", "participant_display_name": "Time participant", "source_step_id": "Step 2"},
            {"participant_id": "participant_step_three", "participant_display_name": "Consumer", "source_step_id": "Step 3"},
        ]
    }
    refs = runtime._task_variable_reference_map(
        completed_results=completed,
        dependency_plan={},
        participant=consumer,
        task_graph=task_graph,
    )

    assert refs["step2.final_answer"] == "2026-06-09 17:20"

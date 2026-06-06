from __future__ import annotations

from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime


def main() -> None:
    participant = {
        "participant_id": "participant_alpha",
        "display_name": "Example Agent",
        "parameter_contract": {
            "parameters": [
                {"name": "first_value", "required": True, "runtime_required": True, "blocking": True, "execution_required": True, "values": []},
                {"name": "second_value", "required": True, "runtime_required": True, "blocking": True, "execution_required": True, "values": []},
            ],
            "missing_information": [],
        },
        "runtime_parameters": {},
    }
    task_graph = {
        "graph_id": "graph_parameter_binding_check",
        "selected_participant_ids": ["participant_alpha"],
        "runtime_parameters": {
            "participant_alpha.first_value": "one",
            "Example Agent.second_value": "two",
        },
        "tasks": [],
    }
    runtime = AgentDelegationRuntime()
    selected = runtime._fresh_task_participants(runtime._select_participants(task_graph, [participant]))
    selected = runtime._hydrate_runtime_bindings_for_task(task_graph, selected)
    runtime._apply_task_runtime_parameters_to_selected(selected, task_graph["runtime_parameters"])
    missing = runtime._collect_missing_agent_parameter_fields(selected, dependency_plan={})
    assert missing == [], missing
    assert selected[0]["parameter_contract"]["missing_information"] == [], selected[0]["parameter_contract"]


if __name__ == "__main__":
    main()

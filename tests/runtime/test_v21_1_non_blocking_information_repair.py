from ai_core.workflow.execution_state_repair import ExecutionStateRepair


def test_information_request_with_refinement_fields_does_not_block_execution():
    plan = {
        "planned_steps": [
            {
                "step_id": "collect_missing_info",
                "step_type": "human_interaction",
                "objective": "Gather required details before planning",
                "parameters": {
                    "known": {},
                    "missing_required": ["field_alpha", "field_beta"],
                    "optional": {},
                },
                "execution_ready": False,
                "human_interaction": {
                    "required": True,
                    "prompt": "Please provide refinements.",
                    "fields": ["field_alpha", "field_beta"],
                },
                "next_action": "generate_candidate_list",
                "requires_human_confirmation": False,
                "execution_strategy": ["local_knowledge", "web_evidence", "tool_generation"],
                "depends_on": [],
            }
        ]
    }

    repaired = ExecutionStateRepair().repair(plan)
    step = repaired["planned_steps"][0]

    assert step["execution_ready"] is True
    assert step["parameters"]["missing_required"] == []
    assert set(step["parameters"]["optional"].keys()) == {"field_alpha", "field_beta"}
    assert step["human_interaction"]["required"] is False
    assert repaired["blocking_missing_information"] == {}

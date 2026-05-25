from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime


def test_runtime_generated_agent_profile_parameters_are_advisory_for_execution():
    runtime = AgentDelegationRuntime()
    participants = [{
        "participant_id": "p1",
        "name": "Generated Agent",
        "parameter_contract": {
            "source": "runtime_llm",
            "parameters": [
                {"name": "context_value", "required": True, "values": []},
            ],
        },
        "runtime_parameters": {},
    }]

    assert runtime._collect_missing_agent_parameter_fields(participants)
    assert runtime._collect_missing_agent_parameter_fields(participants, blocking_only=True) == []


def test_explicit_blocking_agent_profile_parameters_still_pause_execution():
    runtime = AgentDelegationRuntime()
    participants = [{
        "participant_id": "p1",
        "name": "Generated Agent",
        "parameter_contract": {
            "source": "runtime_llm",
            "parameters": [
                {"name": "context_value", "required": True, "values": [], "blocking": True},
            ],
        },
        "runtime_parameters": {},
    }]

    fields = runtime._collect_missing_agent_parameter_fields(participants, blocking_only=True)
    assert len(fields) == 1
    assert fields[0]["parameter_name"] == "context_value"

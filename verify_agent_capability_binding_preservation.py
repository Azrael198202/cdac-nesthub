from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime


def main() -> None:
    runtime = AgentDelegationRuntime()
    durable_agent = {
        "participant_id": "agent_a",
        "display_name": "Bound Agent",
        "execution_policy": "runtime_registered_tool",
        "capability_profile": {
            "capability_type": "runtime_registered_tool",
            "tool_id": "example_registered_tool",
        },
        "parameter_contract": {
            "parameters": [{"name": "payload", "required": True}],
            "missing_information": [],
        },
    }
    task_step_participant = {
        "participant_id": "agent_a",
        "display_name": "Bound Agent",
        "execution_policy": "delegate_to_ai_core",
        "capability_profile": {},
        "parameter_contract": {"parameters": [], "missing_information": []},
    }
    merged = runtime._merge_runtime_binding_fields(task_step_participant, durable_agent)
    assert merged["capability_profile"]["tool_id"] == "example_registered_tool"
    assert merged["capability_profile"]["capability_type"] == "runtime_registered_tool"
    assert merged["execution_policy"] == "runtime_registered_tool"
    assert merged["parameter_contract"]["parameters"][0]["name"] == "payload"
    print("agent capability binding preservation: passed")


if __name__ == "__main__":
    main()

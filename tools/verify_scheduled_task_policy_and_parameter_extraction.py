from __future__ import annotations

from auxiliary_brain.studio.service import AgentStudioService


def test_compact_parameter_lines_are_extracted():
    svc = AgentStudioService()
    instruction = """
Create a task named AnyTask.
Step 1:
Call First Agent.
Parameters: interval = 60s
Step 2:
Call Second Agent.
Parameters: to = example@example.invalid subject = sample subject body = sample body text
"""
    values = svc._extract_runtime_parameters_from_instruction(instruction)
    assert values["interval"] == "60s"
    assert values["to"] == "example@example.invalid"
    assert values["subject"] == "sample subject"
    assert values["body"] == "sample body text"
    assert svc._extract_generic_interval_seconds(instruction) == 60


def test_controller_participant_is_derived_from_timing_step():
    svc = AgentStudioService()
    tasks = [
        {"participant_id": "p1", "source_instruction_fragment": "Call First Agent. Parameters: interval = 60s"},
        {"participant_id": "p2", "source_instruction_fragment": "Call Second Agent. Parameters: payload = value"},
    ]
    participants = [{"participant_id": "p1"}, {"participant_id": "p2"}]
    assert svc._derive_execution_controller_participant_ids(tasks=tasks, participants=participants, runtime_parameters={}) == ["p1"]


if __name__ == "__main__":
    test_compact_parameter_lines_are_extracted()
    test_controller_participant_is_derived_from_timing_step()
    print("scheduled task policy and parameter extraction verification passed")

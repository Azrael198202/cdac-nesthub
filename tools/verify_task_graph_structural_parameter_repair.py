from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auxiliary_brain.studio.service import AgentStudioService


def test_task_graph_structural_parameter_repair() -> None:
    svc = AgentStudioService()
    participant = {
        "participant_id": "participant_1",
        "display_name": "SendGmail Agent",
        "capability_profile": {
            "tool_summary": {
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "array",
                            "items": {"type": "string", "format": "email"},
                            "description": "recipient electronic address",
                        },
                        "subject": {"type": "string"},
                    },
                }
            }
        },
    }
    instruction = "Ask SendGmail Agent to send an email to soarwiththewind6@gmail.com with subject test"
    tasks = [
        {
            "participant_id": "participant_1",
            "participant_display_name": "SendGmail Agent",
            "source_instruction_fragment": instruction,
            "runtime_parameters": {"to": "soarwiththewind"},
        }
    ]
    runtime_parameters = {"to": "soarwiththewind"}
    repaired = svc._repair_runtime_parameters_from_structural_spans(
        instruction=instruction,
        tasks=tasks,
        participants=[participant],
        runtime_parameters=runtime_parameters,
    )
    svc._repair_task_runtime_parameters_from_structural_spans(
        instruction=instruction,
        tasks=tasks,
        participants=[participant],
        runtime_parameters=repaired,
    )
    assert repaired["to"] == ["soarwiththewind6@gmail.com"]
    assert repaired["participant_1.to"] == ["soarwiththewind6@gmail.com"]
    assert tasks[0]["runtime_parameters"]["to"] == ["soarwiththewind6@gmail.com"]


if __name__ == "__main__":
    test_task_graph_structural_parameter_repair()
    print("ok")

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auxiliary_brain.studio.service import AgentStudioService


def test_static_validation_blocks_unresolved_agent_and_step_template() -> None:
    svc = AgentStudioService()
    participants = [
        {"participant_id": "participant_time", "display_name": "Time Agent"},
        {"participant_id": "participant_mail", "display_name": "SendGmail Agent"},
    ]
    instruction = """
Create a task named SendCurrentTimeMail.

Step 1:
Call Time Agent.

Step 2:
Call SendMail Agent.

Parameters:
- to: user@example.com
- subject: Current Time
- body: {{Step99.final_answer}}
"""
    result = svc._validate_task_graph_static(
        instruction=instruction,
        participants=participants,
        selected_participants=[],
        generated_participants=[],
        tasks=[],
    )
    assert result["passed"] is False
    classes = {item.get("failure_class") for item in result.get("issues", [])}
    assert "agent_reference_ambiguous" in classes or "agent_reference_not_found" in classes
    assert "template_reference_not_found" in classes


def test_static_validation_passes_known_agent_and_declared_step_template() -> None:
    svc = AgentStudioService()
    participants = [
        {"participant_id": "participant_time", "display_name": "Time Agent"},
        {"participant_id": "participant_mail", "display_name": "SendGmail Agent"},
    ]
    instruction = """
Create a task named SendCurrentTimeMail.

Step 1:
Call Time Agent.

Step 2:
Call SendGmail Agent.

Parameters:
- to: user@example.com
- subject: Current Time
- body: {{Step1.final_answer}}
"""
    result = svc._validate_task_graph_static(
        instruction=instruction,
        participants=participants,
        selected_participants=[],
        generated_participants=[],
        tasks=[],
    )
    assert result["passed"] is True, result


if __name__ == "__main__":
    test_static_validation_blocks_unresolved_agent_and_step_template()
    test_static_validation_passes_known_agent_and_declared_step_template()
    print("v22.1 task graph static validation checks passed")

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from presentation_brain import FailureMessageRenderer


def main() -> None:
    renderer = FailureMessageRenderer()
    report = {
        "report_id": "failure_test",
        "status": "failure_detected",
        "failure_class": "task_graph_static_validation_failed",
        "stage": "create_task_graph",
        "task_name": "ExampleTask",
        "graph_id": "graph_example",
        "failed_checks": [
            {
                "level": "create_task_graph",
                "check": "declared_participant_reference_resolves",
                "passed": False,
                "failure_class": "agent_reference_ambiguous",
                "message": "A declared participant reference did not resolve to an existing durable participant.",
                "reference": "SendMail Agent",
                "line": 7,
                "suggestions": ["SendGmail Agent"],
                "suggested_location": ["agent_reference_resolution"],
            },
            {
                "level": "create_task_graph",
                "check": "template_step_reference_exists",
                "passed": False,
                "failure_class": "template_reference_not_found",
                "message": "A template reference points to a step that is not declared in this task instruction.",
                "reference": "{{Step99.final_answer}}",
                "declared_steps": ["step1", "step2"],
                "suggested_location": ["task_graph_static_validation"],
            },
        ],
        "suggested_location": ["auxiliary_brain.studio.create_task_graph"],
    }
    message = renderer.render(report, allow_llm=False).to_dict()
    assert message["title"] == "Task graph creation failed"
    assert message["summary"]
    joined = "\n".join(message["reasons"] + message["suggestions"] + message["location"])
    assert "SendMail Agent" in joined
    assert "SendGmail Agent" in joined
    assert "Step99" in joined
    assert "step1" in joined and "step2" in joined
    assert message["source"] == "presentation_brain.deterministic_renderer"
    print("verify_v22_1_failure_message_presentation: passed")


if __name__ == "__main__":
    main()

from __future__ import annotations

from ai_core.workflow.workflow_normalizer import WorkflowNormalizer
from ai_core.workflow.execution_state_repair import ExecutionStateRepair


def main() -> None:
    raw_plan = {
        "planned_steps": [
            {
                "step_id": "step_read_only_example",
                "task_id": "task_read_only_example",
                "task_type": "domain.query",
                "action": "query_information",
                "objective": "Retrieve requested information using available capability.",
                "parameters": {
                    "known": {"entity": "sample", "date": "2099-01-01"},
                    "missing_required": {
                        "time_range": {
                            "label": "Time range",
                            "question": "Which range?"
                        }
                    },
                    "optional": {},
                },
                "required_capability": {"capability_action": "query_information", "status": "available"},
                "execution_ready": False,
                "depends_on": [],
                "requires_human_confirmation": False,
            }
        ]
    }
    normalized = WorkflowNormalizer().normalize(raw_plan)
    repaired = ExecutionStateRepair().repair(normalized, runtime_context={"current_date": "2099-01-01"})
    step = repaired["planned_steps"][0]
    assert step["execution_ready"] is True, step
    assert step["parameters"]["missing_required"] in ({}, []), step
    assert "time_range" in step["parameters"]["optional"], step
    assert repaired["blocking_missing_information"] == {}, repaired
    print("smoke_test_v56: OK")


if __name__ == "__main__":
    main()

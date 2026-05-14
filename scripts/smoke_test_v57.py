from ai_core.executors.tool_call_executor import ToolCallExecutor
from ai_core.workflow.workflow_normalizer import WorkflowNormalizer


def main():
    raw_plan = {
        "planned_steps": [
            {
                "task_id": "generic_information_request",
                "task_type": "information.retrieve.query",
                "action": "get_result",
                "objective": "Retrieve requested information for the requested date.",
                "parameters": {
                    "known": {"entity": "sample", "date": "2099-01-02"},
                    "missing_required": {
                        "time_range": {
                            "label": "Time Range",
                            "question": "Which time range?",
                        }
                    },
                    "optional": {},
                },
                "required_capability": {
                    "capability_action": "get_result",
                    "purpose": "Retrieve external information.",
                    "status": "available",
                },
                "execution_ready": False,
                "depends_on": [],
                "requires_human_confirmation": False,
            }
        ]
    }
    normalized = WorkflowNormalizer().normalize(raw_plan)
    executor = ToolCallExecutor()
    repaired_step = executor._repair_single_step_before_execution(normalized["planned_steps"][0], {"runtime_context": {}})
    assert repaired_step["execution_ready"] is True, repaired_step
    assert repaired_step["parameters"]["missing_required"] in ({}, []), repaired_step
    assert "time_range" in repaired_step["parameters"]["optional"], repaired_step
    assert executor._capability_name(repaired_step["required_capability"]) == "get_result"
    print("smoke_test_v57: OK")


if __name__ == "__main__":
    main()

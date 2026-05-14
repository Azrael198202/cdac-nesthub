from ai_core.executors.tool_call_executor import ToolCallExecutor
from ai_core.execution.continuation_engine import ContinuationEngine
from ai_core.interaction.question_generator import QuestionGenerator
from ai_core.workflow.workflow_normalizer import WorkflowNormalizer


def main():
    raw_plan = {
        "planned_steps": [
            {
                "task_id": "generic_external_lookup",
                "task_type": "information.lookup.query",
                "action": "retrieve_detailed_result",
                "objective": "Retrieve requested external information.",
                "parameters": {
                    "known": {"subject": "sample", "date": "2099-01-02"},
                    "missing_required": [],
                    "optional": {},
                },
                "required_capability": "external_lookup",
                "execution_ready": True,
                "depends_on": [],
                "requires_human_confirmation": False,
                "human_interaction": {
                    "requires_confirmation": False,
                    "confirmation_message": "",
                },
            }
        ]
    }
    executor = ToolCallExecutor()
    normalized = WorkflowNormalizer().normalize(raw_plan)
    repaired = executor._repair_single_step_before_execution(normalized["planned_steps"][0], {"runtime_context": {}})
    repaired = executor.state_consistency.repair_step(repaired)
    hi = executor._normalize_human_interaction(repaired.get("human_interaction"))

    assert repaired["execution_ready"] is True, repaired
    assert executor._missing_fields(repaired) == [], repaired
    assert hi.get("required") is False, hi
    assert executor.state_consistency.should_request_human_information(repaired, hi) is False, (repaired, hi)

    empty_request = QuestionGenerator().build_request([], user_input="sample", language="en")
    # Continuation engine must not create a human pending action for a non-actionable contract.
    pending = ContinuationEngine().build_pending_action(
        "execution",
        {"human_interactions": [{"step_id": "s1", "fields": [], "source_step": repaired}]},
        {"input": "sample", "results": {}},
    )
    assert pending is None, pending
    assert empty_request.get("fields") == [], empty_request
    print("smoke_test_v58: OK")


if __name__ == "__main__":
    main()

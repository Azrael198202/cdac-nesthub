from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.runtime.self_repair import FailureReport, RuntimeSelfRepairEngine
from ai_core.runtime.self_repair.final_answer_guard import FinalAnswerGuard


def assert_schema_repair() -> None:
    engine = RuntimeSelfRepairEngine()
    result = engine.repair(FailureReport(
        stage="pre_execution_validation",
        message="schema validation failed: expected array",
        payload={"input": {"recipient": "a@example.test", "count": "2"}},
        expected_contract={"input_schema": {
            "type": "object",
            "required": ["recipient", "count"],
            "properties": {
                "recipient": {"type": "array"},
                "count": {"type": "integer"}
            }
        }},
    ))
    assert result.applied, result.to_dict()
    assert result.repaired_payload["recipient"] == ["a@example.test"]
    assert result.repaired_payload["count"] == 2
    assert result.validation["passed"] is True


def assert_variable_repair() -> None:
    engine = RuntimeSelfRepairEngine()
    result = engine.repair(FailureReport(
        stage="execution",
        message="unresolved variable binding",
        payload={"parameters": {"body": "{{Step1.final_answer}}"}},
        runtime_state={"steps": {"Step1": {"final_answer": "resolved value"}}},
    ))
    assert result.applied, result.to_dict()
    assert result.repaired_payload["body"] == "resolved value"


def assert_parameter_repair() -> None:
    engine = RuntimeSelfRepairEngine()
    result = engine.repair(FailureReport(
        stage="requirement_completion",
        message="missing required parameter",
        payload={"parameters": {"provided_name": "value"}},
        expected_contract={
            "required_parameters": ["required_name"],
            "parameter_aliases": {"required_name": ["provided_name"]},
        },
    ))
    assert result.applied, result.to_dict()
    assert result.repaired_payload["required_name"] == "value"


def assert_final_answer_guard() -> None:
    guard = FinalAnswerGuard()
    blocked = guard.evaluate(
        requested_external_action=True,
        result_material={"verified": False, "external_action_executed": False},
        draft_answer="The action completed successfully.",
    )
    assert blocked["passed"] is False
    allowed = guard.evaluate(
        requested_external_action=True,
        result_material={"verified": True, "external_action_executed": True},
        draft_answer="The action completed successfully.",
    )
    assert allowed["passed"] is True


if __name__ == "__main__":
    assert_schema_repair()
    assert_variable_repair()
    assert_parameter_repair()
    assert_final_answer_guard()
    print("Runtime Self-Repair Engine verification passed")

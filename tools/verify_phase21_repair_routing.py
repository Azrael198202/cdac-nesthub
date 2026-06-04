from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.runtime.self_repair.repair_orchestrator import FeedbackRepairOrchestrator
from ai_core.runtime.self_repair.execution_failure_repair import ExecutionFailureRepairClassifier


def main() -> None:
    orch = FeedbackRepairOrchestrator()
    parameter = orch.propose_for_tool_result(
        run_id="verify_phase21_parameter_route",
        tool_id="generic_runtime_tool",
        profile_id="default",
        result={"status": "error", "error": {"code": "tool_input_schema_validation_failed", "message": "required value is missing"}},
        tool_spec={"tool_id": "generic_runtime_tool", "implementation": {"type": "runtime_python"}},
        input_payload={},
        expected_contract={"input_schema": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}},
        runtime_state={},
    )
    assert parameter["interaction_kind"] == "input_update_required"
    assert parameter["repair_owner"] == "user"
    assert parameter["requires_user_action"] is True
    assert parameter["requires_user_confirmation"] is False

    secret = orch.propose_for_tool_result(
        run_id="verify_phase21_secret_route",
        tool_id="generic_runtime_tool",
        profile_id="default",
        result={"status": "error", "error": {"code": "tool_execution_failed", "message": "credential not accepted"}},
        tool_spec={"tool_id": "generic_runtime_tool", "implementation": {"type": "runtime_python"}},
        input_payload={"target": "value"},
        expected_contract={},
        runtime_state={},
    )
    assert secret["interaction_kind"] == "profile_secret_update_required"
    assert secret["repair_owner"] == "user"
    assert secret["requires_user_action"] is True
    assert secret["requires_user_confirmation"] is False

    impl = orch.propose_for_tool_result(
        run_id="verify_phase21_impl_route",
        tool_id="generic_runtime_tool",
        profile_id="default",
        result={"status": "error", "error": {"code": "tool_execution_failed", "message": "ImportError: module load failed"}},
        tool_spec={"tool_id": "generic_runtime_tool", "implementation": {"type": "runtime_python"}},
        input_payload={"target": "value"},
        expected_contract={},
        runtime_state={},
    )
    assert impl["interaction_kind"] == "capability_patch_confirmation"
    assert impl["repair_owner"] == "auxiliary_brain"
    assert impl["requires_user_confirmation"] is True

    classifier = ExecutionFailureRepairClassifier()
    assert classifier.classify(result={"status": "error", "error": {"code": "tool_execution_failed", "message": "invalid format"}}, tool_spec={}).category == "parameter_problem"
    print("phase2.1 repair routing verification passed")


if __name__ == "__main__":
    main()

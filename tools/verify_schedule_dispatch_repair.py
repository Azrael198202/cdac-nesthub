from __future__ import annotations

from ai_core.runtime.self_repair.execution_failure_repair import ExecutionFailureRepairClassifier
from auxiliary_brain.studio.service import AgentStudioService


def test_timeout_is_external_not_patch():
    d = ExecutionFailureRepairClassifier().classify(result={"status":"error", "error":{"code":"tool_execution_failed", "message":"timed out"}}, tool_spec={"implementation":{"entrypoint":"tool.py"}})
    assert d.category == "external_service_problem", d


def test_schedule_policy_arms_without_immediate_execution():
    svc = AgentStudioService()
    policy = {"enabled": True, "mode": "recurring", "interval_seconds": 60}
    assert svc._should_pause_for_durable_schedule(policy, scheduled_dispatch=False) is True
    assert svc._should_pause_for_durable_schedule(policy, scheduled_dispatch=True) is False


def test_interval_is_schedule_signal_and_controller_detected():
    svc = AgentStudioService()
    policy = svc._extract_schedule_policy_from_instruction("Step 1: Parameters: interval = 60s")
    assert policy.get("enabled") is True
    assert policy.get("interval_seconds") == 60
    ids = svc._schedule_controller_participant_ids_from_tasks([
        {"participant_id":"p1", "source_instruction_fragment":"Call controller. Parameters: interval = 60s"},
        {"participant_id":"p2", "source_instruction_fragment":"Call worker with payload"},
    ])
    assert ids == ["p1"]


if __name__ == "__main__":
    test_timeout_is_external_not_patch()
    test_schedule_policy_arms_without_immediate_execution()
    test_interval_is_schedule_signal_and_controller_detected()
    print("schedule dispatch repair verification passed")

from __future__ import annotations

from verification_brain import RuntimeVerificationBrain, VerificationExpectation
from verification_brain.foundation import RuntimeVerificationFoundation


def _names(result):
    return {c.get('name') for c in result.checks if c.get('passed') is False}


def main() -> None:
    verifier = RuntimeVerificationBrain()

    r1 = verifier.verify(output={"run_payload": {"final_answer": "{{Step99.final_answer}}"}}, expectation=VerificationExpectation(name="t", rules={}))
    assert not r1.passed and "template_must_be_resolved" in _names(r1)

    r2 = verifier.verify(output={"output": {"status": "completed"}}, expectation=VerificationExpectation(name="s", rules={"required_keys": ["payload"]}))
    assert not r2.passed and "required_key_present" in _names(r2)

    r3 = verifier.verify(output={"task_graph": {"selected_participant_ids": ["p1"]}, "run_payload": {"agent_results": []}}, expectation=VerificationExpectation(name="d", rules={}))
    assert not r3.passed and "selected_participants_have_results" in _names(r3)

    r4 = verifier.verify(output={
        "participants": [{"participant_id": "p1", "capability_profile": {"capability_type": "runtime_registered_tool", "tool_id": "generic_tool"}}],
        "run_payload": {"agent_results": [{"participant_id": "p1", "status": "completed", "workflow_results": {"status": "completed"}}]},
    }, expectation=VerificationExpectation(name="c", rules={}))
    assert not r4.passed and "bound_capability_must_execute_through_registered_path" in _names(r4)

    r5 = verifier.verify(output={"run_payload": {"status": "completed", "final_answer": "None"}}, expectation=VerificationExpectation(name="e", rules={}))
    assert not r5.passed and "final_answer_must_not_be_placeholder_value" in _names(r5)

    r6 = verifier.verify(output={"run_payload": {"agent_results": [{"participant_id": "p1", "status": "completed", "workflow_results": {"tool_id": "generic_tool", "status": "failed"}}]}}, expectation=VerificationExpectation(name="x", rules={}))
    assert not r6.passed and "side_effect_capability_reports_success" in _names(r6)

    foundation = RuntimeVerificationFoundation()
    report = foundation.inspect_run(
        task_graph={"task_name": "V20FailureTask", "selected_participant_ids": ["p1"]},
        participants=[],
        run_payload={"task_name": "V20FailureTask", "run_id": "v20_test_run", "status": "completed", "final_answer": "{{missing.value}}", "agent_results": []},
    )
    assert report is not None
    assert report.failure_class == "template_resolution_problem"
    assert report.failed_checks
    print("v20 verification brain checks passed")


if __name__ == "__main__":
    main()


def _test_level5_llm_expectation_escalation() -> None:
    class FakeResult:
        status = "completed"
        content = '{"passed": true, "confidence": 0.82, "reason": "Runtime output matches the stated expectation.", "suggested_location": ["expectation verifier"]}'
        error = ""
        route = {"brain": "verification_brain", "task_type": "expectation_judgment", "model": "policy_selected"}

    class FakeLLM:
        def __init__(self):
            self.calls = []
        def complete_sync(self, **kwargs):
            self.calls.append(kwargs)
            return FakeResult()

    verifier = RuntimeVerificationBrain()
    fake = FakeLLM()
    verifier.llm = fake
    result = verifier.verify(
        output={
            "task_graph": {"task_name": "GenericTask", "instruction": "Return a concise result for the requested operation."},
            "run_payload": {"status": "completed", "final_answer": "Operation completed successfully.", "agent_results": []},
        },
        expectation=VerificationExpectation(name="llm_exp", rules={"enable_llm_expectation_verification": True}),
    )
    checks = result.checks
    names = {c.get("name") for c in checks}
    assert "llm_expectation_judgment" in names
    llm_check = [c for c in checks if c.get("name") == "llm_expectation_judgment"][0]
    assert llm_check.get("passed") is True
    assert fake.calls and fake.calls[0]["brain"] == "verification_brain"
    assert fake.calls[0]["task_type"] == "expectation_judgment"


if __name__ == "__main__":
    _test_level5_llm_expectation_escalation()

from ai_core.runtime.verification.failure_taxonomy import FailureClassifier, FailureKind
from ai_core.runtime.verification.evidence_contract import EvidenceContractValidator
from ai_core.runtime.verification.execution_assertions import ExecutionAssertions
from ai_core.runtime.verification.generated_execution_validator import GeneratedExecutionValidator
from ai_core.runtime.verification.regression_replay import RegressionReplayRunner


def test_failure_taxonomy():
    assert FailureClassifier().classify({"code": "fetch_timeout"}) == FailureKind.FETCH_FAILED
    assert FailureClassifier().classify({"reason": "extract_error"}) == FailureKind.EXTRACT_FAILED


def test_evidence_contract_validator():
    material = {"source_url": "https://example.test", "facts": [{"value": "19", "confidence": 0.8}]}
    assert EvidenceContractValidator().validate(material)["passed"] is True
    assert EvidenceContractValidator().validate({"facts": []})["passed"] is False


def test_execution_assertions():
    result = ExecutionAssertions().require_events(
        ["local_lookup", "fetch_selected_pages", "dom_extract", "materialize", "synthesize"],
        ["fetch_selected_pages", "dom_extract", "materialize", "synthesize"],
    )
    assert result["passed"] is True


def test_generated_execution_validator():
    good = {"data": {"source_url": "https://example.test", "structured_evidence": [{"value": "x"}]}}
    bad = {"data": {"value": "synthetic"}}
    assert GeneratedExecutionValidator().validate(good)["passed"] is True
    assert GeneratedExecutionValidator().validate(bad)["passed"] is False


def test_regression_replay_runner():
    scenarios = [{"name": "case1", "expected": True}, {"name": "case2", "expected": False}]
    def executor(s):
        return {"passed": s["expected"]}
    results = RegressionReplayRunner().run(scenarios, executor)
    assert [r["passed"] for r in results] == [True, False]

from ai_core.execution.evidence_quality_validator import EvidenceQualityValidator


def test_runtime_parameter_coverage():
    validator = EvidenceQualityValidator()
    payload = {"known": {"entity": "Sample Place", "date": "2026-05-15", "detail_level": "detailed"}}
    result = validator.validate(
        result={"status": "success", "data": {"extracted_text": "Sample Place detailed result for 05-15: high 26, low 15, metric 0."}},
        payload=payload,
        evidence_text="Sample Place detailed result for 05-15: high 26, low 15, metric 0.",
    )
    assert result["passed"] is True


def test_missing_parameter_fails():
    validator = EvidenceQualityValidator()
    payload = {"known": {"entity": "Sample Place", "date": "2026-05-15"}}
    result = validator.validate(
        result={"status": "success", "data": {"extracted_text": "Different entity result."}},
        payload=payload,
        evidence_text="Different entity result.",
    )
    assert result["passed"] is False

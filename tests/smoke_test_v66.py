from ai_core.execution.evidence_quality_validator import EvidenceQualityValidator


def test_generic_evidence_quality_accepts_runtime_parameters():
    validator = EvidenceQualityValidator()
    payload = {"known": {"entity": "Sample Place", "date": "2026-05-15"}}
    result = validator.validate(
        result={"status": "success", "data": {"extracted_text": "Sample Place result for 2026-05-15: value 27 unit, metric 0 unit."}},
        payload=payload,
        evidence_text="Sample Place result for 2026-05-15: value 27 unit, metric 0 unit",
    )
    assert result["passed"] is True

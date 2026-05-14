from ai_core.execution.evidence_quality_validator import EvidenceQualityValidator


def test_rejects_sample_material_without_runtime_terms():
    payload = {"known": {"location": "Fukuoka", "date": "2026-05-15", "detail_level": "detailed"}}
    result = {"status": "success", "data": {"extracted_text": '"date_epoch": 1572739200\n"time_epoch": 1572739200\n"wind_mph": 15.2', "source_name": "API docs"}}
    quality = EvidenceQualityValidator().validate_result(result, payload)
    assert quality["passed"] is False
    assert "location" in quality["missing_keys"] or "date" in quality["missing_keys"]
    assert quality["example_like"] is True


def test_accepts_material_covering_runtime_terms():
    payload = {"known": {"location": "Fukuoka", "date": "2026-05-15"}}
    result = {"status": "success", "data": {"extracted_text": "Fukuoka forecast for May 15: high 26 C, low 15 C, rain 0 mm."}}
    quality = EvidenceQualityValidator().validate_result(result, payload)
    assert quality["passed"] is True

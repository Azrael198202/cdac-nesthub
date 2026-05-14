from ai_core.research.endpoint_resolver import EndpointResolver
from ai_core.execution.candidate_result_synthesizer import CandidateResultSynthesizer
from ai_core.tools.generic_web_extract_artifact import GenericWebExtractArtifactFactory


def test_endpoint_resolver_api_subdomain_variant():
    resolver = EndpointResolver()
    endpoints = resolver.resolve_text(
        "The API endpoint /v1/forecast accepts a geographical coordinate and returns JSON.",
        base_url="https://example.com/docs",
        source="unit",
    )
    urls = {item.url for item in endpoints}
    assert "https://example.com/v1/forecast" in urls
    assert "https://api.example.com/v1/forecast" in urls


def test_candidate_synthesizer_selects_high_quality_success():
    attempts = [
        {"attempt_index": 1, "status": "failed", "candidate": {"score": 100}},
        {
            "attempt_index": 2,
            "status": "success",
            "candidate": {"score": 80, "name": "candidate"},
            "result": {"status": "success", "data": {"retrieval": {"used_live_fetch": True}, "answer_material_quality": {"passed": True, "score": 1.0}}},
        },
    ]
    out = CandidateResultSynthesizer().choose(attempts)
    assert out and out["status"] == "success"
    assert out["result"]["fallback"]["parallel_candidate_evaluation"]["selected_attempt_index"] == 2


def test_generic_web_extract_contract_shape():
    artifact = GenericWebExtractArtifactFactory().build_artifact(capability="external_information_access", candidate={"url": "https://example.com", "name": "Example"})
    assert "tool.py" in artifact["files"]
    assert "def run(payload: dict) -> dict" in artifact["files"]["tool.py"]
    assert artifact["manifest"]["implementation"]["function"] == "run"

from ai_core.research.endpoint_candidate_extractor import EndpointCandidateExtractor


def test_endpoint_candidate_extractor_handles_relative_paths():
    extractor = EndpointCandidateExtractor()
    urls = extractor.extract(
        base_urls=["https://example.com/docs"],
        texts=["The endpoint /v1/result accepts parameters and returns JSON."],
    )
    assert "https://example.com/v1/result" in urls
    assert "https://api.example.com/v1/result" in urls

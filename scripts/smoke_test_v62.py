from ai_core.execution.result_classifier import ResultClassifier
from ai_core.execution.candidate_extractor import CandidateExtractor


def test_result_classifier():
    classifier = ResultClassifier()
    assert classifier.classify({"status": "success", "data": {}})["success"] is True
    assert classifier.classify({"status": "error", "error": {"message": "HTTP Error 403: Forbidden"}})["retryable"] is True
    assert classifier.classify({"status": "error", "error": {"message": "timed out after 60 seconds"}})["category"] == "timeout"


def test_candidate_extractor():
    discovery = {
        "result": {
            "selected_candidate": {"name": "a", "official_documentation_url": "https://example.com/a"},
            "candidates": [
                {"name": "a", "official_documentation_url": "https://example.com/a"},
                {"name": "b", "official_documentation_url": "https://example.com/b"},
            ],
        },
        "documentation_evidence": [
            {"document": {"url": "https://example.com/c", "title": "c"}}
        ],
    }
    candidates = CandidateExtractor().extract(discovery)
    urls = [c["official_documentation_url"] for c in candidates]
    assert urls == ["https://example.com/a", "https://example.com/b", "https://example.com/c"]


if __name__ == "__main__":
    test_result_classifier()
    test_candidate_extractor()
    print("smoke_test_v62: OK")

from ai_core.runtime.semantic.evidence_claim_ranker import EvidenceClaimRanker


def test_best_claim_prefers_stronger_current_release_identifier():
    materials = [
        {
            "source": "verified_external",
            "content": {
                "source_documents": [
                    {"source_url": "https://example.org/release/", "text": "Current stable release 2.4 was published today."},
                    {"source_url": "https://mirror.example.net/info", "text": "Older release 1.9 remains documented."},
                ]
            },
        }
    ]
    ranker = EvidenceClaimRanker()
    claims = ranker.extract_from_materials(materials)
    best = ranker.best_claim(claims)
    assert best is not None
    assert best["value"] == "2.4"


def test_answer_consistency_rejects_older_identifier_than_evidence():
    ranker = EvidenceClaimRanker()
    claims = ranker.extract_from_materials([
        {"source_url": "https://example.org", "content": {"text": "Latest stable release 3.0 is available."}}
    ])
    result = ranker.answer_consistent("The latest stable release is 2.0.", claims)
    assert result["passed"] is False
    assert result["reason"] == "answer_older_than_best_evidence"

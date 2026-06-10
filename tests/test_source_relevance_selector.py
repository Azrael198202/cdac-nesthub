from ai_core.runtime.semantic import SourceRelevanceSelector, EvidenceClaimRanker


def test_selects_only_query_relevant_sources_up_to_five():
    selector = SourceRelevanceSelector()
    cards = [
        {"title": "Alpha tool release 3", "url": "https://a.example/release", "text": "Alpha tool current stable version 3 is released."},
        {"title": "Unrelated cooking", "url": "https://b.example/food", "text": "A recipe with 18 ingredients."},
        {"title": "Alpha tool docs", "url": "https://docs.example/alpha", "text": "Alpha tool version 2 documentation."},
    ]
    result = selector.select(user_input="latest stable Alpha tool version", source_cards=cards, max_sources=5)
    urls = result["selected_urls"]
    assert "https://a.example/release" in urls
    assert "https://docs.example/alpha" in urls
    assert "https://b.example/food" not in urls
    assert len(urls) <= 5


def test_claim_rank_prefers_higher_release_identifier_before_source_rank():
    ranker = EvidenceClaimRanker()
    claims = ranker.extract_from_materials([
        {"source_url": "https://official.example", "text": "Current stable release 15 is available."},
        {"source_url": "https://third.example", "text": "Latest stable release 18 is available."},
    ])
    best = ranker.best_claim(claims)
    assert best["value"] == "18"
    assert ranker.answer_consistent("The answer says release 15.", claims)["passed"] is False

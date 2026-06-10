from ai_core.runtime.reasoning import EvidenceNormalizationLayer, ClaimResolutionLayer, AnswerPlanningLayer


def test_resolves_latest_release_over_testing_candidate():
    cards = [
        {"title": "Official page", "url": "https://example.org/", "text": "You can find information about all of the 19 features and changes. We encourage you to test new features to eliminate bugs and issues.", "relevance_score": 0.9},
        {"title": "Release notes", "url": "https://example.org/release/", "text": "Release Notes: 18 stable release. 17 older release.", "relevance_score": 0.8},
    ]
    normalized = EvidenceNormalizationLayer().normalize(user_input="latest stable version", source_cards=cards)
    resolved = ClaimResolutionLayer().resolve(user_input="latest stable version", normalized_evidence=normalized)
    plan = AnswerPlanningLayer().plan(user_input="latest stable version", resolved_claims=resolved)
    answer = AnswerPlanningLayer().render(plan)
    assert plan["status"] == "ready"
    assert plan["primary_fact"]["value"] == "18"
    assert "19" not in answer.split("Verified latest supported value:", 1)[-1].split(".", 1)[0]


def test_no_raw_source_dump_when_no_structured_fact():
    cards = [
        {"title": "Current conditions", "url": "https://example.org/weather", "text": "Today and tonight forecast, conditions and radar from a weather site.", "relevance_score": 0.9},
    ]
    normalized = EvidenceNormalizationLayer().normalize(user_input="newest information", source_cards=cards)
    resolved = ClaimResolutionLayer().resolve(user_input="newest information", normalized_evidence=normalized)
    plan = AnswerPlanningLayer().plan(user_input="newest information", resolved_claims=resolved)
    answer = AnswerPlanningLayer().render(plan)
    assert plan["status"] == "insufficient"
    assert "Most relevant extracted text fields" not in answer
    assert "Today and tonight forecast" not in answer


def test_structured_measurements_render_as_user_answer():
    cards = [
        {"title": "Current conditions", "url": "https://example.org/current", "text": "Current conditions: temperature 26°C, humidity 70%, wind 8 km/h.", "relevance_score": 0.9},
    ]
    normalized = EvidenceNormalizationLayer().normalize(user_input="current information", source_cards=cards)
    resolved = ClaimResolutionLayer().resolve(user_input="current information", normalized_evidence=normalized)
    plan = AnswerPlanningLayer().plan(user_input="current information", resolved_claims=resolved)
    answer = AnswerPlanningLayer().render(plan)
    assert plan["status"] == "ready"
    assert "26°C" in answer
    assert "70%" in answer
    assert "Most relevant extracted text fields" not in answer

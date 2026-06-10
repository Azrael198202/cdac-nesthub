from ai_core.runtime.reasoning import ContentExtractionLayer, ClaimResolutionLayer, EvidenceNormalizationLayer, AnswerPlanningLayer, AnswerQualityGate


def test_content_records_flow_into_answer_plan():
    docs = [{
        "url": "https://source.example/list",
        "title": "Current updates",
        "dom_evidence_items": [
            {"text": "Updated 10:30 Major public update affects transportation services in a large city"},
        ],
    }]
    extracted = ContentExtractionLayer().extract(fetched_documents=docs)
    normalized = EvidenceNormalizationLayer().normalize(user_input="provide latest items", source_cards=extracted)
    resolved = ClaimResolutionLayer().resolve(user_input="provide latest items", normalized_evidence=normalized)
    plan = AnswerPlanningLayer().plan(user_input="provide latest items", resolved_claims=resolved)
    rendered = AnswerPlanningLayer().render(plan)
    assert plan["status"] == "ready"
    assert "Publication time" in rendered
    assert "transportation" in rendered


def test_answer_quality_gate_rejects_source_only_dump():
    gate = AnswerQualityGate()
    result = gate.evaluate(answer="Sources:\n- https://a.example\n- https://b.example", answer_plan={}, resolved_claims={"facts": []})
    assert result["passed"] is False

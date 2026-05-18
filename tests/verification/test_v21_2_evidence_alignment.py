from ai_core.execution.answer_sufficiency_evaluator import AnswerSufficiencyEvaluator
from ai_core.execution.evidence_direct_answer import EvidenceDirectAnswerBuilder


def test_sufficiency_rejects_numeric_but_misaligned_evidence():
    evaluator = AnswerSufficiencyEvaluator()
    result = evaluator.evaluate(
        user_input="Please summarize AlphaPlace and create a three segment plan.",
        objective="Summarize AlphaPlace and create a plan with ordered segments.",
        capability="generic_information_access",
        known_parameters={"target": "AlphaPlace", "opaque": "X9Z"},
        evidence=[
            {
                "url": "https://example.test/archive/alphaplace",
                "title": "AlphaPlace X9Z archive",
                "text_excerpt": "AlphaPlace X9Z archive. Item 13. Item 28. File 2017. Size 11.81 KB. Count 476.",
                "document": {"text_excerpt": "AlphaPlace X9Z archive. Item 13. Item 28. File 2017. Size 11.81 KB. Count 476."},
            }
        ],
    )
    assert result["passed"] is False
    assert result["aggregate_lexical_signal"] < 0.2


def test_sufficiency_accepts_aligned_evidence_and_ignores_opaque_artifact():
    evaluator = AnswerSufficiencyEvaluator()
    result = evaluator.evaluate(
        user_input="Please summarize AlphaPlace and create a three segment plan.",
        objective="Summarize AlphaPlace and create a plan with ordered segments.",
        capability="generic_information_access",
        known_parameters={"target": "AlphaPlace", "opaque": "X9Z"},
        evidence=[
            {
                "url": "https://example.test/guide/alphaplace",
                "title": "AlphaPlace guide",
                "text_excerpt": "AlphaPlace summary with an ordered plan. Segment one starts at 09:00, segment two starts at 12:00, and segment three starts at 16:00.",
                "document": {"text_excerpt": "AlphaPlace summary with an ordered plan. Segment one starts at 09:00, segment two starts at 12:00, and segment three starts at 16:00."},
            }
        ],
    )
    assert result["passed"] is True
    assert "opaque" not in result["aggregate_coverage"]["missing"]


def test_direct_answer_builder_prefers_aligned_candidate():
    builder = EvidenceDirectAnswerBuilder()
    payload = {
        "parameters": {"known": {"target": "AlphaPlace", "opaque": "X9Z"}},
        "context": {"user_input": "Please summarize AlphaPlace and create a three segment plan."},
        "source_step": {"objective": "Summarize AlphaPlace and create a plan with ordered segments."},
    }
    candidates = [
        {
            "url": "https://example.test/archive/alphaplace",
            "title": "AlphaPlace X9Z archive",
            "score": 90,
            "text_excerpt": "AlphaPlace X9Z archive. Item 13. Item 28. File 2017. Size 11.81 KB. Count 476.",
        },
        {
            "url": "https://example.test/guide/alphaplace",
            "title": "AlphaPlace guide",
            "score": 10,
            "text_excerpt": "AlphaPlace summary with an ordered plan. Segment one starts at 09:00, segment two starts at 12:00, and segment three starts at 16:00.",
        },
    ]
    result = builder.build(candidates=candidates, payload=payload, capability="generic_information_access")
    assert result is not None
    assert result["data"]["source_url"] == "https://example.test/guide/alphaplace"

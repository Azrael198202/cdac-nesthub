from ai_core.execution.answer_sufficiency_evaluator import AnswerSufficiencyEvaluator
from ai_core.execution.evidence_direct_answer import EvidenceDirectAnswerBuilder
from ai_core.utils.semantic_surface import RuntimeSemanticSurfaceNormalizer


def test_compact_duration_is_converted_to_request_surface_and_not_matched_directly():
    evaluator = AnswerSufficiencyEvaluator()
    request = "Please prepare a 3-day plan for AlphaPlace with ordered stops."

    bad = {"title": "AlphaPlace archive", "text_excerpt": "AlphaPlace P3D binary bundle reference only with unrelated compact artifacts, placeholder metadata, opaque rows, and enough body material for runtime validation."}
    good = {"title": "AlphaPlace plan", "text_excerpt": "AlphaPlace 3-day plan with ordered stops, time blocks, source notes, section summaries, verified records, reusable planning details, and enough body material for runtime validation."}

    result = evaluator.evaluate(
        user_input=request,
        objective="prepare ordered result",
        capability="generic_research",
        known_parameters={"target": "AlphaPlace", "period": "P3D"},
        evidence=[bad, good],
    )

    assert result["passed"] is True
    assert result["aggregate_coverage"]["matched"]["period"] != ["p3d"]
    assert "3-day" in result["aggregate_coverage"]["matched"]["period"]
    assert result["selected_evidence"][0]["title"] == "AlphaPlace plan"


def test_compact_duration_without_request_surface_is_dropped_from_known_parameters():
    evaluator = AnswerSufficiencyEvaluator()
    result = evaluator.evaluate(
        user_input="Find material about AlphaPlace.",
        objective="collect useful evidence",
        capability="generic_research",
        known_parameters={"target": "AlphaPlace", "period": "P5D"},
        evidence=[{"title": "AlphaPlace page", "text_excerpt": "AlphaPlace contains useful factual sections, verified records, reusable details, enough body material for runtime validation, and no compact temporal surface."}],
    )
    assert "period" not in result["aggregate_coverage"].get("missing", [])


def test_direct_answer_builder_outputs_surface_known_parameter():
    builder = EvidenceDirectAnswerBuilder()
    result = builder.build(
        candidates=[{"title": "AlphaPlace guide", "url": "https://example.test/a", "text_excerpt": "AlphaPlace 5-day plan with multiple ordered sections, verified records, reusable details, enough body material for runtime validation, and a clear non-compact period surface.", "score": 1}],
        payload={"user_input": "Create a 5-day plan for AlphaPlace.", "known": {"target": "AlphaPlace", "period": "P5D"}},
        capability="generic_research",
    )
    assert result is not None
    assert result["data"]["known_parameters"]["period"] == "5-day"


def test_semantic_surface_normalizer_omits_compact_token_from_aliases():
    normalizer = RuntimeSemanticSurfaceNormalizer()
    aliases = normalizer.semantic_aliases("P3D", "make a 3-day output")
    lowered = [x.lower() for x in aliases]
    assert "p3d" not in lowered
    assert "3-day" in lowered

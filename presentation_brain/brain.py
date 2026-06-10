from __future__ import annotations

from typing import Any

from presentation_brain.contracts import PresentationRequest, PresentationResult
from ai_core.presentation.final_answer_synthesizer import FinalAnswerSynthesizer
from ai_core.presentation.result_material_builder import ResultMaterialBuilder
from ai_core.presentation.result_presenter import ResultPresenter
from presentation_brain.link_renderer import LinkRenderer


class PresentationBrain:
    """Presentation and delivery brain.

    Responsibilities:
    - assemble final answers from existing execution, verification, and evidence
      material;
    - format user-facing responses and reports;
    - preserve provenance and trust summaries;
    - never execute tools, search, repair, or invent new facts.

    This module is intentionally domain-neutral.  It can present any runtime
    result as long as the result is represented with generic state/material
    contracts.
    """

    def __init__(self) -> None:
        self.presenter = ResultPresenter()
        self.material_builder = ResultMaterialBuilder()
        self.synthesizer = FinalAnswerSynthesizer()
        self.link_renderer = LinkRenderer()

    async def synthesize(self, request: PresentationRequest) -> PresentationResult:
        synthesis = await self.synthesizer.synthesize(
            run_id=request.run_id,
            node_id=request.node_id,
            state=request.state,
            materials=request.materials,
            trust_summary=request.trust_summary,
        )
        answer = str(synthesis.get("answer") or "").strip()
        if not answer:
            answer = "Workflow finished, but no verified user-facing answer was produced."
        answer = self.link_renderer.render(answer, source_titles=self.link_renderer.source_titles_from_materials(request.materials))
        return PresentationResult(
            status="completed",
            final_answer=answer,
            message=answer,
            result_material=synthesis.get("result_material") if isinstance(synthesis.get("result_material"), list) else [],
            synthesis=synthesis.get("synthesis") if isinstance(synthesis.get("synthesis"), dict) else {},
            delivery_format=str(request.output_policy.get("delivery_format") or "text"),
        )

    def material_from_execution_step(self, step: dict[str, Any]) -> dict[str, Any]:
        return self.material_builder.from_execution_step(step).to_dict()


__all__ = ["PresentationBrain", "PresentationRequest", "PresentationResult"]

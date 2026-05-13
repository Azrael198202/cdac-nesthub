from __future__ import annotations

from typing import Any

from ai_core.interaction.interaction_contract_generator import InteractionContractGenerator


class QuestionGenerator:
    """Compatibility wrapper for the v39 interaction contract generator."""

    def __init__(self) -> None:
        self.generator = InteractionContractGenerator()

    def build_request(
        self,
        interactions: list[dict[str, Any]],
        *,
        user_input: str = "",
        language: str | None = None,
    ) -> dict[str, Any]:
        return self.generator.build_request(
            interactions,
            user_input=user_input,
            language=language,
        )

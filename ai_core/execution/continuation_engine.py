from __future__ import annotations

from typing import Any

from ai_core.interaction.question_generator import QuestionGenerator


class ContinuationEngine:
    """Decides how a workflow should pause or continue after an execution result."""

    def __init__(self) -> None:
        self.question_generator = QuestionGenerator()

    def build_pending_action(self, node_id: str, result: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None

        state = state or {}
        human_interactions = result.get("human_interactions") or []
        if human_interactions:
            language = self._detect_language(state)
            request = self.question_generator.build_request(
                human_interactions,
                user_input=str(state.get("input", "")),
                language=language,
            )
            return {
                "kind": "human_information_required",
                "node_id": node_id,
                "request": request,
                "result": result,
            }

        missing_tools = result.get("missing_tools") or []
        if missing_tools:
            return {
                "kind": "generated_capability_review",
                "node_id": node_id,
                "missing_tools": missing_tools,
                "result": result,
                "message": "Runtime generated missing tool/module requests and is waiting for review or implementation.",
            }

        safety_holds = result.get("safety_holds") or []
        if safety_holds:
            return {
                "kind": "human_confirmation_required",
                "node_id": node_id,
                "safety_holds": safety_holds,
                "result": result,
                "message": "Human confirmation is required before irreversible or sensitive execution continues.",
            }

        return None

    def _detect_language(self, state: dict[str, Any]) -> str | None:
        results = state.get("results", {}) if isinstance(state, dict) else {}
        for node_id in ["input_parsing", "intent_recognition", "workflow_planning"]:
            result = results.get(node_id)
            if isinstance(result, dict):
                language = result.get("language") or result.get("user_language")
                if isinstance(language, str) and language.strip():
                    return language.strip()
        return None

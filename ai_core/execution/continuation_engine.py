from __future__ import annotations

from typing import Any

from ai_core.interaction.question_generator import QuestionGenerator
from ai_core.interaction.interaction_contract_validator import InteractionContractValidator


class ContinuationEngine:
    """Decides how a workflow should pause or continue after an execution result."""

    def __init__(self) -> None:
        self.question_generator = QuestionGenerator()
        self.contract_validator = InteractionContractValidator()

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
            request = self.contract_validator.validate_or_none(request)
            if request is not None:
                return {
                    "kind": "human_information_required",
                    "node_id": node_id,
                    "request": request,
                    "result": result,
                }

        optional_interactions = result.get("optional_human_interactions") or []
        if optional_interactions:
            return {
                "kind": "optional_credential_choice",
                "node_id": node_id,
                "request": self._build_optional_credential_request(optional_interactions),
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

    def _build_optional_credential_request(self, interactions: list[dict[str, Any]]) -> dict[str, Any]:
        first = interactions[0] if interactions and isinstance(interactions[0], dict) else {}
        return {
            "type": "credential_optional_upgrade",
            "title": first.get("title") or "Optional API Key Available",
            "message": first.get("message") or "A credential-protected provider may improve the result. You can provide an API key or continue without it.",
            "required": False,
            "provider": first.get("provider") or (first.get("api_source") or {}).get("provider") if isinstance(first.get("api_source"), dict) else first.get("provider"),
            "api_source": first.get("api_source") or {},
            "api_sources": first.get("api_sources") or first.get("candidates") or [],
            "secret_fields": first.get("secret_fields") or [
                {
                    "name": "credential",
                    "label": "API Key / Credential",
                    "interaction_type": "secret",
                    "required": False,
                    "placeholder": "Paste API key here",
                }
            ],
            "actions": first.get("actions") or [
                {"id": "continue_without_key", "label": "Continue without API key"},
                {"id": "provide_credential", "label": "Provide API key and continue"},
            ],
            "options": first.get("options") or [
                {"id": "continue_without_key", "label": "Continue without API key"},
                {"id": "provide_credential", "label": "Provide API key and continue"},
            ],
            "interactions": interactions,
        }

    def _detect_language(self, state: dict[str, Any]) -> str | None:
        results = state.get("results", {}) if isinstance(state, dict) else {}
        for node_id in ["input_parsing", "intent_recognition", "workflow_planning"]:
            result = results.get(node_id)
            if isinstance(result, dict):
                language = result.get("language") or result.get("user_language")
                if isinstance(language, str) and language.strip():
                    return language.strip()
        return None

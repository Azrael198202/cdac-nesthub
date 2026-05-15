from __future__ import annotations

from typing import Any


class ModelCapabilityMatcher:
    """Rank provider routes using runtime model tags/capabilities.

    This stays provider-neutral: the matcher does not know model vendors. It only
    reads runtime configuration fields such as `model_tags`, `capabilities`, and
    `role_model_preferences`.
    """

    DEFAULT_ROLE_PREFERENCES: dict[str, list[str]] = {
        "information_retrieval_agent": ["structured_extraction", "reasoning"],
        "workflow_planning_agent": ["workflow_planning", "reasoning", "json_generation"],
        "integration_builder_agent": ["reasoning", "structured_extraction", "json_generation"],
        "code_generation_agent": ["reasoning", "json_generation"],
        "data_analysis_agent": ["structured_extraction", "reasoning"],
        "document_writer_agent": ["document_generation", "reasoning"],
        "human_interaction_agent": ["json_generation"],
        "vision_runtime_agent": ["vision", "screenshot_analysis", "ui_understanding", "reasoning"],
        "general_runtime_agent": ["reasoning", "json_generation"],
    }

    def rank_route(self, *, route: list[str], providers: dict[str, Any], config: dict[str, Any], adapter: dict[str, Any]) -> list[str]:
        if not route:
            return route
        role_id = str(adapter.get("runtime_role") or adapter.get("role_id") or "general_runtime_agent")
        required = self._required_capabilities(role_id=role_id, config=config, adapter=adapter)
        if not required:
            return route

        scored: list[tuple[int, int, str]] = []
        for original_index, provider_name in enumerate(route):
            provider = providers.get(provider_name, {}) or {}
            score = self._score_provider(provider, required)
            # Keep original order as tie-breaker.
            scored.append((-score, original_index, provider_name))
        scored.sort()
        return [name for _, _, name in scored]

    def _required_capabilities(self, *, role_id: str, config: dict[str, Any], adapter: dict[str, Any]) -> list[str]:
        explicit = adapter.get("required_model_capabilities") or adapter.get("model_capabilities")
        if isinstance(explicit, list):
            return [str(x) for x in explicit if str(x).strip()]
        prefs = config.get("role_model_preferences") if isinstance(config.get("role_model_preferences"), dict) else {}
        values = prefs.get(role_id) or self.DEFAULT_ROLE_PREFERENCES.get(role_id) or self.DEFAULT_ROLE_PREFERENCES["general_runtime_agent"]
        return [str(x) for x in values if str(x).strip()]

    def _score_provider(self, provider: dict[str, Any], required: list[str]) -> int:
        tags = set(str(x).lower() for x in (provider.get("model_tags") or []) if str(x).strip())
        capabilities = set(str(x).lower() for x in (provider.get("capabilities") or []) if str(x).strip())
        available = tags | capabilities
        score = 0
        for item in required:
            if item.lower() in available:
                score += 10
        if provider.get("source") == "runtime_model_discovery":
            score += 1
        if provider.get("interactive_key_required") or provider.get("auth_type"):
            # External/keyed providers are still valid, but do not outrank local
            # providers when both satisfy the role.
            score -= 1
        if not provider.get("enabled", False):
            score -= 1000
        return score

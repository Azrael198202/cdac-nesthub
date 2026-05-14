from __future__ import annotations

from typing import Any


class CapabilityResolutionDecision:
    """Decide how to resolve a missing capability without domain knowledge.

    The decision is based only on runtime evidence and generic execution needs:
    existing registry availability, external information requirements, candidate
    evidence, and whether executable code must be generated.
    """

    def decide(
        self,
        *,
        has_registered_tool: bool = False,
        has_registered_module: bool = False,
        requires_external_data: bool | None = None,
        api_discovery: dict[str, Any] | None = None,
        external_discovery: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if has_registered_tool:
            return {
                "resolution_type": "registered_tool",
                "needs_code_generation": False,
                "candidate_strategy": "use_registered_tool",
            }
        if has_registered_module:
            return {
                "resolution_type": "registered_module",
                "needs_code_generation": False,
                "candidate_strategy": "use_registered_module",
            }

        has_api_evidence = self._has_api_or_web_evidence(api_discovery)
        has_external_evidence = self._has_external_evidence(external_discovery)
        if requires_external_data is True or has_api_evidence or has_external_evidence:
            return {
                "resolution_type": "external_information_lookup",
                "needs_code_generation": True,
                "candidate_strategy": "api_web_candidate_pool",
                "notes": "Generate or select an executable adapter only after candidate verification and scoring.",
            }

        return {
            "resolution_type": "missing_runtime_capability",
            "needs_code_generation": True,
            "candidate_strategy": "generate_runtime_capability",
        }

    def _has_api_or_web_evidence(self, value: dict[str, Any] | None) -> bool:
        if not isinstance(value, dict):
            return False
        result = value.get("result") if isinstance(value.get("result"), dict) else {}
        return bool(
            result.get("candidates")
            or result.get("selected_candidate")
            or value.get("web_evidence")
            or value.get("documentation_evidence")
        )

    def _has_external_evidence(self, value: dict[str, Any] | None) -> bool:
        if not isinstance(value, dict):
            return False
        return bool(value.get("documents") or value.get("web_results") or value.get("repositories") or value.get("models"))

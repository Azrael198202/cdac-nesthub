from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class RoleProfile:
    """A compact, domain-neutral runtime role profile.

    The role profile is derived from intent/planning signals and used to scope
    downstream prompts. It is not a business agent and does not contain provider
    or domain-specific execution logic.
    """

    role_id: str
    role_type: str
    required_skills: list[str]
    prompt_policy: dict[str, Any]
    selection_signals: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RoleProfileSelector:
    """Select a compact role profile from runtime state.

    This selector intentionally uses generic action/capability signals such as
    query, fetch, generate, write, analyze, integrate, and interact. It avoids
    business/domain vocabularies so ai_core remains reusable.
    """

    DEFAULT_POLICIES: dict[str, dict[str, Any]] = {
        "information_retrieval_agent": {
            "max_context_tokens": 3000,
            "include_full_trace": False,
            "include_full_html": False,
            "include_only_evidence_summary": True,
            "max_previous_result_items": 8,
            "max_evidence_items": 5,
            "max_chars_per_evidence": 1200,
        },
        "code_generation_agent": {
            "max_context_tokens": 4500,
            "include_full_trace": False,
            "include_full_html": False,
            "include_only_evidence_summary": True,
            "max_previous_result_items": 10,
            "max_evidence_items": 4,
            "max_chars_per_evidence": 1500,
        },
        "document_writer_agent": {
            "max_context_tokens": 5000,
            "include_full_trace": False,
            "include_full_html": False,
            "include_only_evidence_summary": True,
            "max_previous_result_items": 10,
            "max_evidence_items": 6,
            "max_chars_per_evidence": 1800,
        },
        "data_analysis_agent": {
            "max_context_tokens": 5000,
            "include_full_trace": False,
            "include_full_html": False,
            "include_only_evidence_summary": True,
            "max_previous_result_items": 12,
            "max_evidence_items": 6,
            "max_chars_per_evidence": 1600,
        },
        "integration_builder_agent": {
            "max_context_tokens": 6000,
            "include_full_trace": False,
            "include_full_html": False,
            "include_only_evidence_summary": True,
            "max_previous_result_items": 12,
            "max_evidence_items": 6,
            "max_chars_per_evidence": 1800,
        },
        "human_interaction_agent": {
            "max_context_tokens": 2500,
            "include_full_trace": False,
            "include_full_html": False,
            "include_only_evidence_summary": False,
            "max_previous_result_items": 6,
            "max_evidence_items": 2,
            "max_chars_per_evidence": 800,
        },
        "workflow_planning_agent": {
            "max_context_tokens": 3500,
            "include_full_trace": False,
            "include_full_html": False,
            "include_only_evidence_summary": False,
            "max_previous_result_items": 8,
            "max_evidence_items": 3,
            "max_chars_per_evidence": 1000,
        },
        "general_runtime_agent": {
            "max_context_tokens": 3500,
            "include_full_trace": False,
            "include_full_html": False,
            "include_only_evidence_summary": True,
            "max_previous_result_items": 8,
            "max_evidence_items": 4,
            "max_chars_per_evidence": 1200,
        },
    }

    ROLE_SKILLS: dict[str, list[str]] = {
        "information_retrieval_agent": [
            "extract_runtime_parameters",
            "select_relevant_sources",
            "verify_evidence_coverage",
            "summarize_result",
        ],
        "code_generation_agent": [
            "derive_contract",
            "generate_minimal_artifact",
            "respect_runtime_schema",
            "prepare_for_sandbox_verification",
        ],
        "document_writer_agent": [
            "organize_information",
            "write_clear_output",
            "preserve_user_constraints",
            "avoid_unneeded_trace_details",
        ],
        "data_analysis_agent": [
            "extract_structured_data",
            "compare_values",
            "summarize_findings",
            "preserve_uncertainty",
        ],
        "integration_builder_agent": [
            "understand_protocol",
            "identify_authentication_requirements",
            "map_parameters",
            "prepare_adapter_contract",
        ],
        "human_interaction_agent": [
            "ask_minimal_questions",
            "separate_required_and_optional_inputs",
            "protect_sensitive_fields",
        ],
        "workflow_planning_agent": [
            "build_minimal_steps",
            "preserve_ready_state",
            "avoid_tool_selection_when_unneeded",
        ],
        "general_runtime_agent": [
            "follow_schema",
            "use_compact_context",
            "avoid_debug_dump",
        ],
    }

    def select(self, *, node_id: str | None, state: dict[str, Any], adapter: dict[str, Any] | None = None) -> RoleProfile:
        adapter = adapter or {}
        explicit = adapter.get("role_id") or adapter.get("runtime_role")
        if explicit:
            return self._profile(str(explicit), ["adapter_explicit_role"])

        text = self._collect_signals(node_id=node_id, state=state)
        signals: list[str] = []
        role_id = "general_runtime_agent"

        # Contract-level routing has priority over wording-level routing.  A
        # step can ask for a written summary while also requiring source
        # material; in that case the planning prompt must remain retrieval-
        # scoped until evidence has been collected.  This is structural and
        # domain-neutral: it only checks runtime contracts and execution method
        # identifiers, not task topics.
        if self._state_requires_source_material(state):
            role_id = "information_retrieval_agent"
            signals.append("source_contract_signal")
        elif self._contains_any(text, ["credential", "secret", "approval", "confirm", "interaction", "human"]):
            role_id = "human_interaction_agent"
            signals.append("interaction_signal")
        elif self._contains_any(text, ["adapter", "protocol", "endpoint", "authentication", "schema", "integration", "connector"]):
            role_id = "integration_builder_agent"
            signals.append("integration_signal")
        elif self._contains_any(text, ["code", "module", "artifact", "sandbox", "generate", "implementation"]):
            role_id = "code_generation_agent"
            signals.append("generation_signal")
        elif self._contains_any(text, ["query", "lookup", "search", "fetch", "retrieve", "evidence", "source"]):
            role_id = "information_retrieval_agent"
            signals.append("retrieval_signal")
        elif self._contains_any(text, ["write", "document", "report", "summary", "presentation", "compose"]):
            role_id = "document_writer_agent"
            signals.append("writing_signal")
        elif self._contains_any(text, ["analyze", "compare", "calculate", "metric", "table", "dataset"]):
            role_id = "data_analysis_agent"
            signals.append("analysis_signal")
        elif node_id and "planning" in str(node_id).lower():
            role_id = "workflow_planning_agent"
            signals.append("planning_node_signal")

        return self._profile(role_id, signals or ["default_signal"])


    def _state_requires_source_material(self, state: dict[str, Any]) -> bool:
        """Return true when runtime contracts require sourced material.

        The method intentionally does not look for topical words.  It walks the
        current state and checks generic source/evidence contract flags and
        locked execution methods.
        """
        def walk(value: Any, depth: int = 0) -> bool:
            if depth > 8:
                return False
            if isinstance(value, dict):
                if value.get("requires_source_material") is True:
                    return True
                if value.get("requires_live_evidence") is True:
                    return True
                if value.get("evidence_required") is True:
                    return True
                if value.get("needs_web_search") is True:
                    return True
                method = str(value.get("execution_method") or value.get("selected_execution_method") or value.get("action_type") or "").strip()
                if method in {"web_query", "web_search"}:
                    return True
                contract_type = str(value.get("contract_type") or "").strip()
                if "source" in contract_type and value.get("requires_source_material") is not False:
                    return True
                return any(walk(v, depth + 1) for v in value.values())
            if isinstance(value, list):
                return any(walk(v, depth + 1) for v in value[:80])
            return False

        return walk(state)

    def _profile(self, role_id: str, signals: list[str]) -> RoleProfile:
        if role_id not in self.DEFAULT_POLICIES:
            role_id = "general_runtime_agent"
        return RoleProfile(
            role_id=role_id,
            role_type=role_id.replace("_agent", ""),
            required_skills=self.ROLE_SKILLS.get(role_id, self.ROLE_SKILLS["general_runtime_agent"]),
            prompt_policy=dict(self.DEFAULT_POLICIES[role_id]),
            selection_signals=signals,
        )

    def _collect_signals(self, *, node_id: str | None, state: dict[str, Any]) -> str:
        parts: list[str] = [str(node_id or ""), str(state.get("input", ""))]
        results = state.get("results") or {}
        if isinstance(results, dict):
            for key, value in results.items():
                parts.append(str(key))
                if isinstance(value, dict):
                    for field in ("intent_type", "task_type", "action", "required_capability", "required_capabilities", "next_action"):
                        parts.append(str(value.get(field, "")))
                    tasks = value.get("tasks") or value.get("planned_steps") or []
                    if isinstance(tasks, list):
                        for item in tasks[:5]:
                            parts.append(str(item))
        return " ".join(parts).lower()

    @staticmethod
    def _contains_any(text: str, terms: list[str]) -> bool:
        return any(term in text for term in terms)

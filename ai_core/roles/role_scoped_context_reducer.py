from __future__ import annotations

from typing import Any

from ai_core.context.evidence_noise_reducer import EvidenceNoiseReducer
from ai_core.utils.safe_json import make_json_safe


class RoleScopedContextReducer:
    """Reduce runtime context according to the selected role profile.

    This prevents downstream LLM calls from receiving full traces, raw HTML,
    endpoint checks, and repeated discovery payloads when only compact evidence
    or final step state is needed.
    """

    LARGE_KEYS = {
        "text_excerpt",
        "sample",
        "stdout",
        "stderr",
        "raw_html",
        "html",
        "page_content",
        "checks",
        "resolved_endpoint_candidates",
        "documentation_evidence",
        "documents",
        "web_results",
        "web_evidence",
        "external_solution_discovery",
        "api_discovery",
        "endpoint_verification",
        "trace_path",
        "web_research_trace",
    }

    KEEP_STEP_KEYS = {
        "status",
        "intent_type",
        "language",
        "parsed_entities",
        "temporal_expressions",
        "semantic_modifiers",
        "missing_information",
        "required_capabilities",
        "blocking_missing_information",
        "planned_steps",
        "tasks",
        "execution_ready",
        "final_answer",
        "answer",
        "result",
        "tool_results",
        "human_interaction",
        "execution_status",
    }

    def __init__(self) -> None:
        self.evidence_reducer = EvidenceNoiseReducer()

    def reduce_state(self, *, state: dict[str, Any], capability_result: dict[str, Any] | None, role_profile: dict[str, Any]) -> dict[str, Any]:
        policy = role_profile.get("prompt_policy", {}) if isinstance(role_profile, dict) else {}
        max_items = int(policy.get("max_previous_result_items") or 8)
        max_chars = int(policy.get("max_chars_per_evidence") or 1200)
        include_evidence_summary = bool(policy.get("include_only_evidence_summary", True))

        results = state.get("results") if isinstance(state.get("results"), dict) else {}
        compact_results: dict[str, Any] = {}
        for index, (key, value) in enumerate(results.items()):
            if index >= max_items:
                compact_results["_truncated"] = f"Only first {max_items} result entries included by role policy."
                break
            compact_results[key] = self._compact_value(value, max_chars=max_chars)

        compact_capability = self._compact_value(capability_result or {}, max_chars=max_chars)
        evidence_summary = None
        if include_evidence_summary:
            evidence_summary = self._build_evidence_summary(state=state, capability_result=capability_result or {}, role_profile=role_profile)

        return {
            "input": state.get("input", ""),
            "run_id": state.get("run_id"),
            "role_profile": role_profile,
            "previous_results": compact_results,
            "capability_result": compact_capability,
            "evidence_summary": evidence_summary,
            "human_feedback": state.get("human_feedback", []),
        }

    def _compact_value(self, value: Any, *, max_chars: int) -> Any:
        value = make_json_safe(value)
        if isinstance(value, dict):
            compact: dict[str, Any] = {}
            for key, item in value.items():
                if key in self.LARGE_KEYS:
                    continue
                if key in self.KEEP_STEP_KEYS or len(compact) < 24:
                    compact[key] = self._compact_value(item, max_chars=max_chars)
            return compact
        if isinstance(value, list):
            return [self._compact_value(item, max_chars=max_chars) for item in value[:12]]
        if isinstance(value, str):
            clean = " ".join(value.split())
            return clean[:max_chars] + ("...[trimmed]" if len(clean) > max_chars else "")
        return value

    def _build_evidence_summary(self, *, state: dict[str, Any], capability_result: dict[str, Any], role_profile: dict[str, Any]) -> dict[str, Any]:
        known = self._extract_known_parameters(state=state, capability_result=capability_result)
        candidates = []
        candidates.extend(self._collect_evidence_objects(capability_result))
        results = state.get("results") or {}
        if isinstance(results, dict):
            for value in results.values():
                candidates.extend(self._collect_evidence_objects(value))

        policy = role_profile.get("prompt_policy", {}) if isinstance(role_profile, dict) else {}
        max_items = int(policy.get("max_evidence_items") or 5)
        max_chars = int(policy.get("max_chars_per_evidence") or 1200)
        reduced = self.evidence_reducer.reduce(
            payload={"evidence": candidates, "known_parameters": known},
            known_parameters=known,
            max_items=max_items,
            max_chars_per_item=max_chars,
        )
        return reduced

    def _extract_known_parameters(self, *, state: dict[str, Any], capability_result: dict[str, Any]) -> dict[str, Any]:
        known: dict[str, Any] = {}
        sources: list[Any] = [capability_result]
        state_results = state.get("results")
        if isinstance(state_results, dict):
            sources.extend(state_results.values())
        for source in sources:
            if not isinstance(source, dict):
                continue
            params = source.get("parameters") if isinstance(source.get("parameters"), dict) else {}
            nested_known = params.get("known") if isinstance(params.get("known"), dict) else {}
            known.update({k: v for k, v in nested_known.items() if v not in (None, "", [], {})})
            semantics = source.get("runtime_request_semantics") if isinstance(source.get("runtime_request_semantics"), dict) else {}
            semantic_known = semantics.get("known_parameters") if isinstance(semantics.get("known_parameters"), dict) else {}
            known.update({k: v for k, v in semantic_known.items() if v not in (None, "", [], {})})
            parsed = source.get("parsed_entities") if isinstance(source.get("parsed_entities"), dict) else {}
            known.update({k: v for k, v in parsed.items() if v not in (None, "", [], {})})
            temporal = source.get("temporal_expressions") if isinstance(source.get("temporal_expressions"), list) else []
            for item in temporal:
                if isinstance(item, dict) and item.get("normalized_value"):
                    known.setdefault("date", item.get("normalized_value"))
        return known

    def _collect_evidence_objects(self, value: Any) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        if isinstance(value, dict):
            if any(k in value for k in ("url", "title", "snippet", "text_excerpt", "document")):
                collected.append(value)
            for key in ("web_evidence", "documentation_evidence", "documents", "web_results", "evidence", "tool_results"):
                nested = value.get(key)
                if isinstance(nested, list):
                    for item in nested[:20]:
                        if isinstance(item, dict):
                            collected.extend(self._collect_evidence_objects(item))
                elif isinstance(nested, dict):
                    collected.extend(self._collect_evidence_objects(nested))
        elif isinstance(value, list):
            for item in value[:20]:
                collected.extend(self._collect_evidence_objects(item))
        return collected

from __future__ import annotations

import json
from typing import Any

from ai_core.llm.provider_router import ProviderRouter
from ai_core.presentation.result_sanitizer import ResultSanitizer
from ai_core.presentation.structured_fact_normalizer import StructuredFactNormalizer
from ai_core.runtime.semantic import SynthesisGuard


class FinalAnswerSynthesizer:
    """Creates final user-facing answers from normalized facts only."""

    DEBUG_MARKERS = ("Matched Parameter:", "Descriptors:", "Values:")

    def __init__(self) -> None:
        self.sanitizer = ResultSanitizer()
        self.normalizer = StructuredFactNormalizer()
        self.router = ProviderRouter()
        self.guard = SynthesisGuard()

    async def synthesize(
        self,
        *,
        run_id: str,
        node_id: str,
        state: dict[str, Any],
        materials: list[dict[str, Any]],
        trust_summary: dict[str, Any],
    ) -> dict[str, Any]:
        sanitized = self.sanitizer.sanitize_materials(materials)
        facts = self.guard.filter(self.normalizer.normalize(materials=sanitized, state=state))
        deterministic = self._deterministic_summary(facts=facts, sanitized=sanitized, trust_summary=trust_summary)
        answer = deterministic

        if self._model_synthesis_enabled(state, facts):
            generated = await self._try_model_synthesis(
                run_id=run_id,
                node_id=node_id,
                state=state,
                facts=facts,
                trust_summary=trust_summary,
            )
            if generated:
                answer = generated

        answer = self._assert_no_debug_material_in_final_answer(answer, fallback=deterministic)
        return {
            "answer": answer,
            "result_material": [{"source": "normalized_fact_pipeline", "status": "success", "content": {"normalized_facts": facts}}],
            "synthesis": {
                "source": "model_or_rule_synthesis" if answer != deterministic else "rule_synthesis",
                "raw_source_material_returned": False,
                "normalized_facts_only": True,
                "verified_facts_only": True,
            },
        }

    def _model_synthesis_enabled(self, state: dict[str, Any], facts: list[dict[str, Any]]) -> bool:
        output_policy = (((state.get("runtime") or {}) if isinstance(state, dict) else {}).get("output_policy") or {})
        if output_policy.get("disable_model_synthesis") is True:
            return False
        output_policy = (((state.get("runtime") or {}) if isinstance(state, dict) else {}).get("output_policy") or {})
        return bool(facts) and output_policy.get("allow_model_synthesis_from_verified_facts") is True

    async def _try_model_synthesis(
        self,
        *,
        run_id: str,
        node_id: str,
        state: dict[str, Any],
        facts: list[dict[str, Any]],
        trust_summary: dict[str, Any],
    ) -> str:
        try:
            prompt_text = json.dumps(
                {
                    "user_request": self._original_input(state),
                    "language": self._language(state),
                    "normalized_facts": facts[:16],
                    "trust": self._compact_trust(trust_summary),
                    "instructions": [
                        "Create a concise user-facing answer.",
                        "Use only normalized_facts.",
                        "Do not include extraction traces or internal labels.",
                        "Do not mention unavailable sources unless facts are insufficient.",
                        "Return JSON with key final_answer only.",
                    ],
                },
                ensure_ascii=False,
            )
            adapter = {
                "adapter_id": "final_answer_synthesizer",
                "provider_route": ["ollama", "openai"],
                "preferred_capabilities": ["structured_output", "summarization"],
                "prompt_policy": {"max_context_tokens": 1800},
            }
            prompt = {"id": "final_answer_synthesis", "system": "Return valid JSON only."}
            schema = {"type": "object", "properties": {"final_answer": {"type": "string"}}, "required": ["final_answer"]}
            result = await self.router.generate_json(
                run_id=run_id,
                node_id=node_id,
                adapter=adapter,
                prompt=prompt,
                rendered_user_prompt=prompt_text,
                schema=schema,
            )
            value = result.get("final_answer") if isinstance(result, dict) else None
            if isinstance(value, str) and value.strip():
                return self.sanitizer.sanitize_value(value).strip()
        except Exception:
            # Provider errors, missing credentials, or local model failures must not
            # prevent deterministic synthesis from normalized facts.
            return ""
        return ""

    def _deterministic_summary(self, *, facts: list[dict[str, Any]], sanitized: list[dict[str, Any]], trust_summary: dict[str, Any]) -> str:
        if facts:
            aligned_records = [f for f in facts if f.get("kind") == "aligned_record"]
            statements = [f for f in facts if f.get("kind") == "supporting_statement"]
            values = [f for f in facts if f.get("kind") not in {"supporting_statement", "aligned_record"}]
            lines: list[str] = []

            if aligned_records:
                lines.append("Details:")
                selected_records = self._best_aligned_records(aligned_records)
                seen_records: set[str] = set()
                for fact in selected_records[:8]:
                    text = self._clean_sentence(str(fact.get("value") or fact.get("context") or ""))
                    if not text or text in seen_records:
                        continue
                    seen_records.add(text)
                    lines.append(f"- {text}")
                sources = []
                for fact in selected_records:
                    src = str(fact.get("source_url") or "")
                    if src.startswith("http") and src not in sources:
                        sources.append(src)
                if sources:
                    lines.append("Source:")
                    lines.append(f"- {sources[0]}")
                answer = "\n".join(line for line in lines if line).strip()
                if answer:
                    return answer

            clean_statements = []
            for fact in statements[:3]:
                text = self._clean_sentence(str(fact.get("value") or fact.get("context") or ""))
                if text and text not in clean_statements:
                    if text[:1] and text[:1].islower():
                        continue
                    clean_statements.append(text)
            if clean_statements:
                lines.append("Summary:")
                lines.extend(f"- {item}" for item in clean_statements[:3])

            value_parts = []
            for fact in values:
                label = self._friendly_label(str(fact.get("label") or "value"))
                value = str(fact.get("value") or "").strip()
                unit = str(fact.get("unit") or "").strip()
                if not value:
                    continue
                if not unit and str(fact.get("semantic_type") or "") != "temporal_marker" and str(fact.get("source_level") or "") != "runtime_native":
                    continue
                if not unit and label == "value":
                    continue
                item = f"{label}: {value}{unit}"
                if item not in value_parts:
                    value_parts.append(item)
                if len(value_parts) >= 10:
                    break
            if value_parts:
                lines.append("Details:")
                lines.extend(f"- {item}" for item in value_parts)

            sources = sorted({str(f.get("source_url")) for f in facts if str(f.get("source_url") or "").startswith("http")})
            if sources:
                lines.append("Source:")
                lines.append(f"- {sources[0]}")
            answer = "\n".join(line for line in lines if line).strip()
            if answer:
                return answer

        # If no facts exist, return a neutral failure without leaking internals.
        if trust_summary and trust_summary.get("verified_real_execution") is False:
            return "I could not produce a verified answer from the available result material."
        return "The runtime completed, but no user-facing answer material was available."

    def _best_aligned_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best_by_target: dict[str, dict[str, Any]] = {}
        untargeted: list[dict[str, Any]] = []
        for record in records:
            target = str(record.get("target") or "")
            if not target:
                untargeted.append(record)
                continue
            existing = best_by_target.get(target)
            if existing is None or float(record.get("confidence") or 0) > float(existing.get("confidence") or 0):
                best_by_target[target] = record
        selected = list(best_by_target.values()) if best_by_target else untargeted
        selected.sort(key=lambda item: (str(item.get("target") or ""), -float(item.get("confidence") or 0)))
        return selected

    def _friendly_label(self, label: str) -> str:
        text = " ".join(str(label or "value").replace("_", " ").split())
        if not text or len(text) > 64:
            return "value"
        return text[:1].upper() + text[1:]

    def _clean_sentence(self, text: str) -> str:
        clean = " ".join(str(text or "").split())
        for marker in self.DEBUG_MARKERS:
            clean = clean.replace(marker, "")
        # Avoid returning long navigation/menu fragments. Keep the part that has
        # measurement signal and a manageable length.
        if len(clean) > 520:
            clean = clean[:520].rsplit(" ", 1)[0]
        return clean.strip(" -;,.|")

    def _assert_no_debug_material_in_final_answer(self, answer: str, *, fallback: str) -> str:
        text = str(answer or "")
        if any(marker in text for marker in self.DEBUG_MARKERS):
            clean = str(fallback or "").strip()
            if clean and not any(marker in clean for marker in self.DEBUG_MARKERS):
                return clean
            return "I found supporting material, but it could not be safely converted into a user-facing answer."
        return text

    def _compact_trust(self, trust_summary: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(trust_summary, dict):
            return {}
        return {k: trust_summary.get(k) for k in ("trust_level", "verified_real_execution", "evidence_quality_passed") if k in trust_summary}

    def _original_input(self, state: dict[str, Any]) -> str:
        for section_name in ("input", "request", "runtime"):
            section = state.get(section_name) if isinstance(state, dict) else None
            if isinstance(section, dict):
                for key in ("original_input", "user_input", "message"):
                    value = section.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            elif section_name == "input" and isinstance(section, str):
                return section
        results = state.get("results") if isinstance(state, dict) else None
        if isinstance(results, dict):
            input_result = results.get("input_parsing")
            if isinstance(input_result, dict):
                value = input_result.get("original_input")
                if isinstance(value, str):
                    return value
        return ""

    def _language(self, state: dict[str, Any]) -> str:
        results = state.get("results") if isinstance(state, dict) else None
        if isinstance(results, dict):
            input_result = results.get("input_parsing")
            if isinstance(input_result, dict):
                value = input_result.get("language")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

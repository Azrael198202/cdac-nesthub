from __future__ import annotations

import json
from typing import Any

from ai_core.llm.provider_router import ProviderRouter
from ai_core.presentation.result_sanitizer import ResultSanitizer
from ai_core.presentation.structured_fact_normalizer import StructuredFactNormalizer
from ai_core.runtime.semantic import SynthesisGuard, EvidenceClaimRanker
from ai_core.runtime.reasoning import EvidenceNormalizationLayer, ClaimResolutionLayer, AnswerPlanningLayer, ContentExtractionLayer, AnswerQualityGate


class FinalAnswerSynthesizer:
    """Creates final user-facing answers from normalized facts only."""

    DEBUG_MARKERS = (
        "Matched Parameter:",
        "Descriptors:",
        "Values:",
        "Use upstream input",
        "Return valid JSON",
        "Return JSON",
        "If the selected action",
        "prompt_contract",
        "output_contract",
        "executor_llm_generation",
        "verification phase",
        "planner_llm",
        "agent_action_prompt_contract",
    )
    INTERNAL_CONTRACT_KEYS = {
        "agent_action_prompt_contract",
        "prompt_contract",
        "output_contract",
        "action_contract",
        "agent_execution_flow",
        "web_collection",
        "api_call_preparation",
        "tool_generation",
        "uploaded_artifact_execution",
        "resource_bundle",
        "contract",
        "contracts",
        "instructions",
        "rules",
        "prompt",
        "system",
        "schema",
    }

    def __init__(self) -> None:
        self.sanitizer = ResultSanitizer()
        self.normalizer = StructuredFactNormalizer()
        self.router = ProviderRouter()
        self.guard = SynthesisGuard()
        self.claim_ranker = EvidenceClaimRanker()
        self.evidence_normalizer = EvidenceNormalizationLayer()
        self.claim_resolver = ClaimResolutionLayer()
        self.answer_planner = AnswerPlanningLayer()
        self.content_extractor = ContentExtractionLayer()
        self.quality_gate = AnswerQualityGate()

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
        extracted_content = self.content_extractor.extract(fetched_documents=self._fetched_documents_from_materials(sanitized))
        normalized_evidence = self.evidence_normalizer.normalize(user_input=self._original_input(state), materials=sanitized, source_cards=extracted_content)
        resolved_claims = self.claim_resolver.resolve(user_input=self._original_input(state), normalized_evidence=normalized_evidence)
        answer_plan = self.answer_planner.plan(user_input=self._original_input(state), resolved_claims=resolved_claims, language=self._language(state))
        planned_answer = self.answer_planner.render(answer_plan)
        evidence_claims = resolved_claims.get("comparable_claims") or self.claim_ranker.extract_from_materials(sanitized)
        direct_answer = self._direct_generated_answer_material(sanitized)
        direct_consistency = self.claim_ranker.answer_consistent(direct_answer, evidence_claims) if direct_answer else {"passed": True}
        direct_quality = self.quality_gate.evaluate(answer=direct_answer, answer_plan=answer_plan, resolved_claims=resolved_claims) if direct_answer else {"passed": False}
        if direct_answer and answer_plan.get("status") == "ready" and direct_consistency.get("passed") is True and direct_quality.get("passed") is True:
            return {
                "answer": direct_answer,
                "result_material": [{"source": "answer_material", "status": "success", "content": {"answer": direct_answer, "evidence_claims": evidence_claims[:8]}}],
                "synthesis": {
                    "source": "direct_answer_material",
                    "raw_source_material_returned": False,
                    "normalized_facts_only": False,
                    "verified_facts_only": False,
                    "answer_evidence_consistency": direct_consistency,
                    "reason": "The locked workflow selected model/content generation and the generated answer is consistent with comparable evidence claims.",
                },
            }
        facts = self.guard.filter(self.normalizer.normalize(materials=sanitized, state=state))
        facts = self.claim_ranker.filter_verified_facts(facts, evidence_claims)
        deterministic = planned_answer if answer_plan.get("status") in {"ready", "insufficient"} else self._deterministic_summary(facts=facts, sanitized=sanitized, trust_summary=trust_summary, evidence_claims=evidence_claims)
        answer = deterministic

        if self._model_synthesis_enabled(state, facts):
            generated = await self._try_model_synthesis(
                run_id=run_id,
                node_id=node_id,
                state=state,
                facts=facts,
                trust_summary=trust_summary,
            )
            generated_consistency = self.claim_ranker.answer_consistent(generated, evidence_claims) if generated else {"passed": False}
            if generated and generated_consistency.get("passed") is True:
                answer = generated

        final_consistency = self.claim_ranker.answer_consistent(answer, evidence_claims)
        final_quality = self.quality_gate.evaluate(answer=answer, answer_plan=answer_plan, resolved_claims=resolved_claims)
        if final_consistency.get("passed") is not True or final_quality.get("passed") is not True:
            answer = deterministic
            final_consistency = self.claim_ranker.answer_consistent(answer, evidence_claims)
            final_quality = self.quality_gate.evaluate(answer=answer, answer_plan=answer_plan, resolved_claims=resolved_claims)
        answer = self._assert_no_debug_material_in_final_answer(answer, fallback=deterministic)
        return {
            "answer": answer,
            "result_material": [{"source": "normalized_fact_pipeline", "status": "success", "content": {"normalized_facts": facts, "normalized_evidence": normalized_evidence, "resolved_claims": resolved_claims, "answer_plan": answer_plan}}],
            "synthesis": {
                "source": "model_or_rule_synthesis" if answer != deterministic else "rule_synthesis",
                "raw_source_material_returned": False,
                "normalized_facts_only": True,
                "verified_facts_only": True,
                "evidence_claim_count": len(evidence_claims),
                "answer_evidence_consistency": final_consistency,
                "answer_quality_gate": final_quality,
            },
        }


    def _fetched_documents_from_materials(self, materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        def visit(value: Any) -> None:
            if isinstance(value, dict):
                has_page_text = any(isinstance(value.get(k), str) and value.get(k).strip() for k in ("text_excerpt", "visible_text_excerpt", "html_excerpt", "dom_evidence_text"))
                has_url = any(isinstance(value.get(k), str) and value.get(k).startswith(("http://", "https://")) for k in ("url", "source_url"))
                if has_page_text or has_url or isinstance(value.get("dom_evidence_items"), list):
                    docs.append(value)
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        visit(child)
            elif isinstance(value, list):
                for item in value[:120]:
                    visit(item)
        visit(materials)
        return docs[:80]


    def _direct_generated_answer_material(self, sanitized: list[dict[str, Any]]) -> str:
        """Return user-facing generated content when it is the planned deliverable.

        Planner prompts, contracts, schemas, and internal instructions must never
        become the final answer. This method therefore only accepts explicit
        public answer fields and skips known internal contract containers.
        """
        public_keys = ("answer_material", "generated_content", "final_answer", "answer")

        def is_public_text(text: str) -> bool:
            clean = self.sanitizer.sanitize_value(text).strip()
            if not clean:
                return False
            if any(marker in clean for marker in self.DEBUG_MARKERS):
                return False
            return True

        def scan(value: Any) -> str:
            if isinstance(value, dict):
                # Prefer explicit public answer material only. Do not read generic
                # "content" from contract/prompt envelopes because those often
                # contain planner instructions.
                for key in public_keys:
                    item = value.get(key)
                    if isinstance(item, str) and is_public_text(item):
                        return self.sanitizer.sanitize_value(item).strip()
                    if isinstance(item, (dict, list)):
                        nested = scan(item)
                        if nested:
                            return nested
                for key, child in value.items():
                    if str(key) in self.INTERNAL_CONTRACT_KEYS:
                        continue
                    if isinstance(child, (dict, list)):
                        nested = scan(child)
                        if nested:
                            return nested
            if isinstance(value, list):
                for item in value[:20]:
                    nested = scan(item)
                    if nested:
                        return nested
            return ""
        return scan(sanitized)

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

    def _deterministic_summary(self, *, facts: list[dict[str, Any]], sanitized: list[dict[str, Any]], trust_summary: dict[str, Any], evidence_claims: list[dict[str, Any]] | None = None) -> str:
        evidence_claims = evidence_claims or []
        best_claim = self.claim_ranker.best_claim(evidence_claims)
        if best_claim:
            best_line = self._best_claim_line(best_claim)
            sources = self._claim_sources(evidence_claims)
            lines = ["I found the strongest evidence-backed claim:", f"- {best_line}"]
            if sources:
                lines.append("Source:")
                lines.append(f"- {sources[0]}")
            return "\n".join(lines).strip()

        if facts:
            aligned_records = [f for f in facts if f.get("kind") == "aligned_record"]
            statements = [f for f in facts if f.get("kind") == "supporting_statement"]
            values = [f for f in facts if f.get("kind") not in {"supporting_statement", "aligned_record"}]
            lines: list[str] = []

            if aligned_records:
                lines.append("I found the following:")
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
                lines.append("I found the following:")
                lines.extend(f"- {item}" for item in value_parts)

            sources = sorted({str(f.get("source_url")) for f in facts if str(f.get("source_url") or "").startswith("http")})
            if sources:
                lines.append("Source:")
                lines.append(f"- {sources[0]}")
            answer = "\n".join(line for line in lines if line).strip()
            if answer:
                return answer

        source_report = self._source_report_from_materials(sanitized)
        if source_report:
            return source_report

        # If no facts exist, return a neutral failure without leaking internals.
        if trust_summary and trust_summary.get("verified_real_execution") is False:
            return "I could not produce a verified answer from the available result material."
        return "The runtime completed, but no user-facing answer material was available."



    def _best_claim_line(self, claim: dict[str, Any]) -> str:
        value = str(claim.get("value") or "").strip()
        status = str(claim.get("status") or "").strip()
        context = self._clean_sentence(str(claim.get("context") or ""))
        if context:
            return context
        if status and status != "unspecified":
            return f"{value} ({status})"
        return value or "verified claim"

    def _claim_sources(self, claims: list[dict[str, Any]]) -> list[str]:
        sources: list[str] = []
        for claim in claims:
            src = str(claim.get("source_url") or "")
            if src.startswith("http") and src not in sources:
                sources.append(src)
        return sources

    def _source_report_from_materials(self, sanitized: list[dict[str, Any]]) -> str:
        sources: list[dict[str, Any]] = []
        consensus: dict[str, Any] = {}

        def visit(value: Any) -> None:
            nonlocal consensus
            if isinstance(value, dict):
                report = value.get("investigation_report")
                if isinstance(report, dict):
                    items = report.get("sources") if isinstance(report.get("sources"), list) else []
                    for item in items[:12]:
                        if isinstance(item, dict):
                            sources.append(item)
                    if not consensus:
                        consensus = report
                summaries = value.get("source_summaries")
                if isinstance(summaries, list):
                    for item in summaries[:12]:
                        if isinstance(item, dict):
                            sources.append(item)
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        visit(child)
            elif isinstance(value, list):
                for item in value[:20]:
                    visit(item)

        visit(sanitized)
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in sources:
            url = str(item.get("url") or item.get("source_url") or "").strip()
            host = str(item.get("host") or "").strip()
            key = url or host
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        if not unique:
            return ""
        lines = ["I could not create a verified final answer from the collected material.", "Investigated sources:"]
        for item in unique[:10]:
            url = str(item.get("url") or item.get("source_url") or "").strip()
            score = item.get("score")
            facts = item.get("fact_count")
            reason = str(item.get("reason") or item.get("status") or "reviewed").strip()
            suffix_parts = []
            if score is not None:
                suffix_parts.append(f"score={score}")
            if facts is not None:
                suffix_parts.append(f"facts={facts}")
            if reason:
                suffix_parts.append(reason)
            suffix = " — " + ", ".join(suffix_parts[:3]) if suffix_parts else ""
            if url:
                lines.append(f"- {url}{suffix}")
        status = str(consensus.get("consensus_status") or consensus.get("status") or "").strip()
        reason = str(consensus.get("consensus_reason") or "").strip()
        if status or reason:
            lines.append("Result:")
            lines.append(f"- Consensus was not sufficient{(': ' + reason) if reason else ''}.")
        return "\n".join(lines).strip()

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

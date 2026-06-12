from __future__ import annotations

from typing import Any

from ai_core.presentation.result_material import ResultMaterial


class ResultMaterialBuilder:
    """Collects generic execution outputs as intermediate material.

    Execution results are not final answers. They are source material for a
    later presentation/synthesis stage.
    """

    TEXT_KEYS = ("answer_material", "generated_content", "final_answer", "answer", "summary", "message", "text")
    INTERNAL_KEYS = {
        "status",
        "source",
        "requires_human_confirmation",
        "provenance",
        "fallback_attempts",
        "raw",
        "debug",
        "trace",
        # Execution contracts/prompts are internal instructions, not user-facing material.
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
    }

    def from_execution_step(self, step: dict[str, Any]) -> ResultMaterial:
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        source = str(result.get("source") or step.get("source") or step.get("step_id") or "runtime")
        status = str(result.get("status") or step.get("status") or "unknown")
        provenance = result.get("provenance") if isinstance(result.get("provenance"), dict) else step.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        quality = self._quality(result)
        content = self._content(result)
        metadata = self._metadata(step, result)
        return ResultMaterial(source=source, status=status, content=content, metadata=metadata, provenance=provenance, quality=quality)

    def _quality(self, result: dict[str, Any]) -> dict[str, Any]:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        candidates = [result.get("answer_material_quality"), data.get("answer_material_quality")]
        for item in candidates:
            if isinstance(item, dict):
                return dict(item)
        return {}

    def _content(self, result: dict[str, Any]) -> Any:
        for key in self.TEXT_KEYS:
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return {key: value.strip()}
        data = result.get("data")
        if isinstance(data, dict):
            # Source-retrieval material must remain structured until the
            # contract-aware formatter validates item count and requested fields.
            # Do not collapse it into generic normalized_facts first.
            source_docs = self._source_documents(data)
            if self._is_source_retrieval_result(result, data):
                public = {k: v for k, v in data.items() if k not in self.INTERNAL_KEYS}
                if source_docs:
                    public["source_documents"] = source_docs
                for key in ("source_contract", "execution_known", "presentation_contract", "prompt_profile", "execution_method"):
                    if key in result and key not in public:
                        public[key] = result.get(key)
                return public
            # Prefer structured runtime evidence over pre-composed answer text.
            # Pre-composed text may contain extractor traces; structured evidence
            # can be normalized and validated by the semantic contract engine.
            if isinstance(data.get("normalized_facts"), list):
                return {
                    "normalized_facts": data.get("normalized_facts"),
                    "source_url": data.get("source_url"),
                    "source_title": data.get("source_title"),
                    "source_documents": source_docs,
                    "source_summaries": data.get("source_summaries"),
                    "investigation_report": data.get("investigation_report"),
                }
            if isinstance(data.get("structured_evidence"), list):
                return {
                    "structured_evidence": data.get("structured_evidence"),
                    "source_documents": source_docs,
                    "source_url": data.get("source_url"),
                    "source_title": data.get("source_title"),
                    "known_parameters": data.get("known_parameters"),
                    "source_summaries": data.get("source_summaries"),
                    "investigation_report": data.get("investigation_report"),
                }
            public = {k: v for k, v in data.items() if k not in self.INTERNAL_KEYS}
            if source_docs:
                public["source_documents"] = source_docs
            return public if public else {}
        if data is not None:
            return data
        if result.get("error"):
            return {"error": result.get("error")}
        return {}


    def _source_documents(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract public document excerpts from nested research evidence.

        This keeps the runtime generic: it does not know any domain. It only
        looks for source URL/title plus visible text excerpts that were produced
        by research tools.
        """
        docs: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if len(docs) >= 6:
                return
            if isinstance(value, dict):
                text = value.get("visible_text_excerpt") or value.get("text_excerpt") or value.get("dom_evidence_text")
                url = value.get("url") or value.get("source_url")
                title = value.get("title") or value.get("source_title") or value.get("name")
                if isinstance(text, str) and text.strip():
                    docs.append({
                        "text": text.strip(),
                        "source_url": str(url or ""),
                        "source_title": str(title or ""),
                    })
                for key in ("selected_evidence", "evidence", "document", "source_search_result", "answer_sufficiency"):
                    if key in value:
                        visit(value.get(key))
                # Scan short lists only; these are usually evidence candidate arrays.
                for key in ("selected_evidence", "candidates", "items"):
                    item = value.get(key)
                    if isinstance(item, list):
                        for child in item[:6]:
                            visit(child)
                # Shallow generic recursion for nested research envelopes. Skip
                # scalar strings because raw page text is captured above via the
                # public excerpt keys.
                for child in value.values():
                    if isinstance(child, dict):
                        visit(child)
                    elif isinstance(child, list) and len(child) <= 8:
                        for nested in child[:6]:
                            if isinstance(nested, (dict, list)):
                                visit(nested)
            elif isinstance(value, list):
                for item in value[:6]:
                    visit(item)

        visit(data)
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for doc in docs:
            key = (doc.get("source_url") or "") + "|" + (doc.get("text") or "")[:120]
            if key in seen:
                continue
            seen.add(key)
            unique.append(doc)
        return unique

    def _is_source_retrieval_result(self, result: dict[str, Any], data: dict[str, Any]) -> bool:
        method = str(result.get("execution_method") or data.get("execution_method") or "").casefold()
        profile = str(result.get("prompt_profile") or data.get("prompt_profile") or "").casefold()
        source_contract = result.get("source_contract") if isinstance(result.get("source_contract"), dict) else data.get("source_contract")
        if isinstance(source_contract, dict) and source_contract.get("requires_source_material") is True:
            return True
        if method in {"web_search", "web_query"} or profile == "source_retrieval":
            return True
        return any(isinstance(data.get(key), list) for key in ("search_results", "fetched_documents", "source_cards"))

    def _metadata(self, step: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for key in ("step_id", "capability", "component_type", "component_id", "source_contract", "execution_known", "semantic_known", "presentation_contract", "prompt_profile", "execution_method"):
            value = step.get(key) or result.get(key)
            if value is not None:
                metadata[key] = value
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        for key in ("source_contract", "execution_known", "semantic_known", "presentation_contract", "prompt_profile", "execution_method"):
            if key not in metadata and data.get(key) is not None:
                metadata[key] = data.get(key)
        return metadata

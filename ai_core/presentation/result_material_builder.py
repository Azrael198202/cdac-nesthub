from __future__ import annotations

from typing import Any

from ai_core.presentation.result_material import ResultMaterial


class ResultMaterialBuilder:
    """Collects generic execution outputs as intermediate material.

    Execution results are not final answers. They are source material for a
    later presentation/synthesis stage.
    """

    TEXT_KEYS = ("final_answer", "answer", "summary", "message", "text")
    INTERNAL_KEYS = {
        "status",
        "source",
        "requires_human_confirmation",
        "provenance",
        "fallback_attempts",
        "raw",
        "debug",
        "trace",
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
            # Prefer structured runtime evidence over pre-composed answer text.
            # Pre-composed text may contain extractor traces; structured evidence
            # can be normalized and validated by the semantic contract engine.
            source_docs = self._source_documents(data)
            if isinstance(data.get("normalized_facts"), list):
                return {
                    "normalized_facts": data.get("normalized_facts"),
                    "source_url": data.get("source_url"),
                    "source_title": data.get("source_title"),
                    "source_documents": source_docs,
                }
            if isinstance(data.get("structured_evidence"), list):
                return {
                    "structured_evidence": data.get("structured_evidence"),
                    "source_documents": source_docs,
                    "source_url": data.get("source_url"),
                    "source_title": data.get("source_title"),
                    "known_parameters": data.get("known_parameters"),
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

    def _metadata(self, step: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for key in ("step_id", "capability", "component_type", "component_id"):
            value = step.get(key) or result.get(key)
            if value is not None:
                metadata[key] = value
        return metadata

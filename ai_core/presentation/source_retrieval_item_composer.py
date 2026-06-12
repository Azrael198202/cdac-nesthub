from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceRetrievalItemComposer:
    """Contract-aware presenter for source retrieval results.

    This component is generic. It does not know any business domain. It only
    reads the compiled source/presentation contracts, extracts public source
    items from search/fetch material, validates requested cardinality and fields,
    and renders an exportable answer. It intentionally bypasses generic
    normalized fact synthesis for source-retrieval steps because page fragments
    and navigation text are not equivalent to requested source items.
    """

    def should_handle(self, *, state: dict[str, Any], materials: list[dict[str, Any]]) -> bool:
        contract = self.source_contract(state=state, materials=materials)
        if contract.get("requires_source_material") is True:
            return True
        fields = self.requested_fields(contract)
        cardinality = self.cardinality(contract)
        if fields and self._contains_source_field(fields):
            return True
        if cardinality.get("requested_count") and fields:
            return True
        return self._has_source_retrieval_marker(state=state, materials=materials)

    def compose(self, *, state: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, Any]:
        contract = self.source_contract(state=state, materials=materials)
        fields = self.requested_fields(contract)
        cardinality = self.cardinality(contract)
        requested_count = self._safe_int(cardinality.get("requested_count"))
        if requested_count <= 0:
            requested_count = self._requested_count_from_execution_known(state=state, materials=materials)
        items = self._collect_items(materials)
        items = self._deduplicate_items(items)
        if requested_count > 0:
            items = items[:requested_count]
        missing = self._validation_errors(items=items, fields=fields, requested_count=requested_count)
        if missing:
            return {
                "status": "failed",
                "answer": "Source retrieval did not produce enough verified material to satisfy the compiled output contract.",
                "result_material": [{
                    "source": "source_retrieval_contract_formatter",
                    "status": "failed",
                    "content": {
                        "items": items,
                        "validation_errors": missing,
                        "source_contract": contract,
                    },
                }],
                "synthesis": {
                    "source": "source_retrieval_contract_formatter",
                    "source_retrieval_contract_applied": True,
                    "exportable": False,
                    "validation_errors": missing,
                },
            }
        answer = self._render(items=items, fields=fields)
        return {
            "status": "completed",
            "answer": answer,
            "result_material": [{
                "source": "source_retrieval_contract_formatter",
                "status": "success",
                "content": {
                    "items": items,
                    "source_contract": contract,
                },
            }],
            "synthesis": {
                "source": "source_retrieval_contract_formatter",
                "source_retrieval_contract_applied": True,
                "normalized_fact_pipeline_bypassed": True,
                "exportable": True,
                "item_count": len(items),
                "requested_count": requested_count,
                "requested_fields": fields,
            },
        }

    def source_contract(self, *, state: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, Any]:
        candidates: list[Any] = []
        if isinstance(state, dict):
            candidates.extend([
                state.get("source_contract"),
                ((state.get("runtime") or {}) if isinstance(state.get("runtime"), dict) else {}).get("source_contract"),
                ((state.get("compiled_step") or {}) if isinstance(state.get("compiled_step"), dict) else {}).get("source_contract"),
            ])
            for key in ("execution_plan", "selected_step", "step", "current_step"):
                value = state.get(key)
                if isinstance(value, dict):
                    candidates.append(value.get("source_contract"))
        for material in materials:
            if not isinstance(material, dict):
                continue
            meta = material.get("metadata") if isinstance(material.get("metadata"), dict) else {}
            content = material.get("content") if isinstance(material.get("content"), dict) else {}
            provenance = material.get("provenance") if isinstance(material.get("provenance"), dict) else {}
            candidates.extend([meta.get("source_contract"), content.get("source_contract"), provenance.get("source_contract")])
            data = content.get("data") if isinstance(content.get("data"), dict) else {}
            candidates.append(data.get("source_contract"))
        merged: dict[str, Any] = {}
        for item in candidates:
            if isinstance(item, dict):
                merged.update({k: v for k, v in item.items() if v not in (None, "", [], {})})
        return merged

    def requested_fields(self, contract: dict[str, Any]) -> list[str]:
        fields = contract.get("requested_output_fields") if isinstance(contract.get("requested_output_fields"), list) else []
        normalized: list[str] = []
        for item in fields:
            field = self._normalize_field(item)
            if field and field not in normalized:
                normalized.append(field)
        return normalized

    def cardinality(self, contract: dict[str, Any]) -> dict[str, Any]:
        card = contract.get("output_cardinality") if isinstance(contract.get("output_cardinality"), dict) else {}
        return dict(card)

    def _collect_items(self, materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raw_items: list[dict[str, Any]] = []

        def add_item(value: dict[str, Any], *, fallback_source: dict[str, Any] | None = None) -> None:
            item = self._item_from_record(value, fallback_source=fallback_source)
            if item:
                raw_items.append(item)

        def visit(value: Any, *, fallback_source: dict[str, Any] | None = None, depth: int = 0) -> None:
            if depth > 8:
                return
            if isinstance(value, dict):
                # Prefer explicit arrays produced by web/search tooling.
                for key in ("search_results", "source_cards", "items", "results", "extracted_content_records", "selected_evidence_blocks", "selected_evidence"):
                    child = value.get(key)
                    if isinstance(child, list):
                        for record in child[:40]:
                            if isinstance(record, dict):
                                add_item(record, fallback_source=fallback_source or value)
                # Fetched document can be represented as a single source item.
                if self._looks_like_public_source_record(value):
                    add_item(value, fallback_source=fallback_source)
                for key in ("data", "content", "result", "document", "source_search_result", "optimized_evidence", "fetched_documents", "source_documents"):
                    child = value.get(key)
                    if isinstance(child, (dict, list)):
                        visit(child, fallback_source=fallback_source or value, depth=depth + 1)
            elif isinstance(value, list):
                for item in value[:80]:
                    visit(item, fallback_source=fallback_source, depth=depth + 1)

        visit(materials)
        return raw_items

    def _item_from_record(self, record: dict[str, Any], *, fallback_source: dict[str, Any] | None = None) -> dict[str, Any]:
        fallback_source = fallback_source if isinstance(fallback_source, dict) else {}
        title = self._clean(record.get("title") or record.get("name") or record.get("source_title") or fallback_source.get("title"))
        summary = self._clean(record.get("summary") or record.get("snippet") or record.get("description") or record.get("text") or record.get("text_excerpt") or record.get("visible_text_excerpt"))
        url = self._clean(record.get("url") or record.get("source_url") or record.get("link") or fallback_source.get("url") or fallback_source.get("source_url"))
        source = self._clean(record.get("source") or record.get("publisher") or record.get("site_name") or record.get("source_name") or record.get("domain") or record.get("source_title"))
        publication_time = self._clean(
            record.get("publication_time") or record.get("published_at") or record.get("published") or record.get("date") or record.get("time") or record.get("time_expression") or record.get("datetime")
        )
        if not source and url:
            source = self._domain_from_url(url)
        if not title:
            title = self._derive_title(summary)
        if not summary:
            summary = self._derive_summary(record)
        if not (title and (url or source)):
            return {}
        item = {
            "title": title,
            "brief_summary": summary,
            "summary": summary,
            "source": source,
            "publication_time": publication_time,
            "url": url,
        }
        return {k: v for k, v in item.items() if v not in (None, "", [], {})}

    def _looks_like_public_source_record(self, value: dict[str, Any]) -> bool:
        has_title = isinstance(value.get("title") or value.get("name") or value.get("source_title"), str)
        has_url = isinstance(value.get("url") or value.get("source_url") or value.get("link"), str)
        has_summary = isinstance(value.get("snippet") or value.get("summary") or value.get("text_excerpt") or value.get("visible_text_excerpt"), str)
        return bool(has_url and (has_title or has_summary))

    def _deduplicate_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("url") or "") or str(item.get("title") or "")).casefold().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _validation_errors(self, *, items: list[dict[str, Any]], fields: list[str], requested_count: int) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        if requested_count > 0 and len(items) < requested_count:
            errors.append({"code": "cardinality_not_satisfied", "requested_count": requested_count, "actual_count": len(items)})
        required_fields = [f for f in fields if f not in {"brief", "for_each_story", "for_each_item"}]
        for index, item in enumerate(items, start=1):
            missing: list[str] = []
            for field in required_fields:
                canonical = self._canonical_field(field)
                if canonical == "brief_summary":
                    ok = bool(item.get("brief_summary") or item.get("summary"))
                elif canonical == "publication_time":
                    ok = bool(item.get("publication_time"))
                else:
                    ok = bool(item.get(canonical))
                if not ok:
                    missing.append(field)
            if missing:
                errors.append({"code": "required_fields_missing", "item_index": index, "missing_fields": missing})
        return errors

    def _render(self, *, items: list[dict[str, Any]], fields: list[str]) -> str:
        if not fields:
            fields = ["title", "brief_summary", "source", "publication_time", "url"]
        lines: list[str] = []
        for index, item in enumerate(items, start=1):
            lines.append(f"{index}.")
            for field in fields:
                canonical = self._canonical_field(field)
                label = self._label_for_field(canonical, original=field)
                if canonical == "brief_summary":
                    value = item.get("brief_summary") or item.get("summary")
                elif canonical == "publication_time":
                    value = item.get("publication_time")
                else:
                    value = item.get(canonical)
                if value:
                    lines.append(f"- {label}: {value}")
            lines.append("")
        return "\n".join(lines).strip()

    def _has_source_retrieval_marker(self, *, state: dict[str, Any], materials: list[dict[str, Any]]) -> bool:
        def scan(value: Any, depth: int = 0) -> bool:
            if depth > 5:
                return False
            if isinstance(value, dict):
                method = str(value.get("execution_method") or value.get("method") or value.get("prompt_profile") or value.get("capability") or "").casefold()
                if method in {"web_search", "web_query", "source_retrieval", "web_retrieval"}:
                    return True
                if value.get("requires_source_material") is True:
                    return True
                return any(scan(child, depth + 1) for child in value.values() if isinstance(child, (dict, list)))
            if isinstance(value, list):
                return any(scan(item, depth + 1) for item in value[:40])
            return False
        return scan(state) or scan(materials)

    def _requested_count_from_execution_known(self, *, state: dict[str, Any], materials: list[dict[str, Any]]) -> int:
        candidates: list[Any] = []
        if isinstance(state, dict):
            candidates.append((state.get("execution_known") or {}).get("requested_count") if isinstance(state.get("execution_known"), dict) else None)
        for material in materials:
            if not isinstance(material, dict):
                continue
            meta = material.get("metadata") if isinstance(material.get("metadata"), dict) else {}
            content = material.get("content") if isinstance(material.get("content"), dict) else {}
            candidates.append((meta.get("execution_known") or {}).get("requested_count") if isinstance(meta.get("execution_known"), dict) else None)
            candidates.append((content.get("execution_known") or {}).get("requested_count") if isinstance(content.get("execution_known"), dict) else None)
        for candidate in candidates:
            count = self._safe_int(candidate)
            if count > 0:
                return count
        return 0

    def _contains_source_field(self, fields: list[str]) -> bool:
        return any(self._canonical_field(field) in {"source", "url", "publication_time"} for field in fields)

    def _canonical_field(self, field: Any) -> str:
        norm = self._normalize_field(field)
        mapping = {
            "brief_summary": "brief_summary",
            "summary": "brief_summary",
            "brief": "brief_summary",
            "source": "source",
            "sources": "source",
            "url": "url",
            "link": "url",
            "publication_time": "publication_time",
            "published_at": "publication_time",
            "published_time": "publication_time",
            "time": "publication_time",
            "date": "publication_time",
            "title": "title",
            "name": "title",
        }
        return mapping.get(norm, norm)

    def _label_for_field(self, canonical: str, *, original: str) -> str:
        labels = {
            "title": "Title",
            "brief_summary": "Brief summary",
            "source": "Source",
            "publication_time": "Publication time",
            "url": "URL",
        }
        return labels.get(canonical, str(original).strip().strip(":：") or canonical)

    def _normalize_field(self, field: Any) -> str:
        text = str(field or "").strip().casefold().strip(":：")
        text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        return text

    def _derive_title(self, text: str) -> str:
        text = self._clean(text)
        if not text:
            return ""
        sentence = re.split(r"(?<=[.!?。！？])\s+", text)[0]
        return sentence[:160].strip()

    def _derive_summary(self, record: dict[str, Any]) -> str:
        for key in ("answer_material", "content", "body", "description"):
            value = self._clean(record.get(key))
            if value:
                return value[:320].strip()
        return ""

    def _domain_from_url(self, url: str) -> str:
        match = re.search(r"https?://([^/]+)/?", url)
        if not match:
            return ""
        return match.group(1).removeprefix("www.")

    def _clean(self, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    def _safe_int(self, value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0

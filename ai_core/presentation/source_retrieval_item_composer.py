from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse


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
        fetched_urls = self._fetched_urls(materials)
        if fetched_urls:
            items = [item for item in items if self._item_has_fetched_url(item, fetched_urls)]
        quality_report = self._quality_report(items=items, state=state, materials=materials)
        items = [item for item in items if item not in quality_report["rejected_items"]]
        items, consistency_report = self._apply_consistency_gate(items)
        consistency_report["quality_gate"] = quality_report["summary"]
        if fields:
            items = self._rank_items_for_fields(items, fields)
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
                        "consistency_report": consistency_report,
                        "quality_report": quality_report["summary"],
                        "source_contract": contract,
                    },
                }],
                "synthesis": {
                    "source": "source_retrieval_contract_formatter",
                    "source_retrieval_contract_applied": True,
                    "exportable": False,
                    "item_count": len(items),
                    "requested_count": requested_count,
                    "requested_fields": fields,
                    "validation_errors": missing,
                    "consistency_report": consistency_report,
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
                    "consistency_report": consistency_report,
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
                "consistency_report": consistency_report,
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
        if not merged:
            merged = self._contract_from_state_text(state=state, materials=materials)
        else:
            derived = self._contract_from_state_text(state=state, materials=materials)
            if derived:
                merged.setdefault("requires_source_material", derived.get("requires_source_material"))
                if not merged.get("requested_output_fields") and derived.get("requested_output_fields"):
                    merged["requested_output_fields"] = derived.get("requested_output_fields")
                card = merged.get("output_cardinality") if isinstance(merged.get("output_cardinality"), dict) else {}
                dcard = derived.get("output_cardinality") if isinstance(derived.get("output_cardinality"), dict) else {}
                if not card.get("requested_count") and dcard.get("requested_count"):
                    merged["output_cardinality"] = {**card, **dcard}
        return {k: v for k, v in merged.items() if v not in (None, "", [], {})}

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



    def _query_terms(self, text: str) -> list[str]:
        stop = {
            "the", "and", "for", "with", "from", "that", "this", "please", "provide", "give", "show",
            "latest", "today", "current", "recent", "each", "story", "stories", "item", "items",
            "title", "summary", "brief", "source", "publication", "time", "url", "link", "news",
        }
        terms: list[str] = []
        for token in re.findall(r"[A-Za-z0-9_+.#/-]{3,}|[\u3040-\u30ff\u3400-\u9fff]{2,}", str(text or "")):
            clean = token.strip(" .,:;()[]{}<>\\\"'`")
            if not clean or clean.casefold() in stop:
                continue
            if clean not in terms:
                terms.append(clean)
            if len(terms) >= 12:
                break
        return terms

    def _quality_report(self, *, items: list[dict[str, Any]], state: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, Any]:
        user_text = self._contract_text(state=state, materials=materials)
        requires_freshness = self._requires_freshness(user_text)
        query_terms = set(term.casefold() for term in self._query_terms(user_text))
        rejected: list[dict[str, Any]] = []
        reasons: list[dict[str, Any]] = []
        for item in items:
            reason = self._source_item_rejection_reason(item=item, requires_freshness=requires_freshness, query_terms=query_terms)
            if reason:
                rejected.append(item)
                reasons.append({
                    "reason": reason,
                    "title": self._clean(item.get("title"))[:180],
                    "url": self._clean(item.get("url"))[:220],
                    "publication_time": self._clean(item.get("publication_time"))[:80],
                })
        return {
            "rejected_items": rejected,
            "summary": {
                "checked_count": len(items),
                "rejected_count": len(rejected),
                "rejection_reasons": reasons[:20],
                "freshness_required": requires_freshness,
            },
        }

    def _source_item_rejection_reason(self, *, item: dict[str, Any], requires_freshness: bool, query_terms: set[str]) -> str:
        title = self._clean(item.get("title"))
        summary = self._clean(item.get("brief_summary") or item.get("summary"))
        url = self._clean(item.get("url"))
        source = self._clean(item.get("source"))
        publication_time = self._clean(item.get("publication_time"))
        combined = f"{title} {summary} {source} {url}".casefold()
        if not (title and summary and (source or url)):
            return "missing_core_source_item_fields"
        if self._looks_like_instructional_or_reference_material(title=title, summary=summary, source=source, url=url):
            return "material_is_reference_or_instructional_content_not_requested_evidence"
        if requires_freshness and not self._publication_time_satisfies_freshness(publication_time):
            return "publication_time_not_fresh_enough_for_request"
        if query_terms:
            hits = sum(1 for term in query_terms if term and term in combined)
            if hits <= 0:
                return "not_relevant_to_retrieval_query"
        if len(summary) < 40:
            return "summary_too_short_for_evidence_item"
        return ""

    def _looks_like_instructional_or_reference_material(self, *, title: str, summary: str, source: str, url: str) -> bool:
        text = f"{title} {summary} {source} {url}".casefold()
        reference_signals = [
            "documentation", "docs", "sdk", "api", "endpoint", "authentication", "pricing", "quota",
            "quick start", "tutorial", "faq", "frequently asked questions", "how to", "see the full",
            "get ", "post ", "delete ", "put ", "parameters", "console", "status page",
        ]
        signal_count = sum(1 for signal in reference_signals if signal in text)
        # This gate is intentionally generic: it rejects records whose own
        # content is primarily an instruction/reference page, not a source item
        # satisfying a requested evidence contract. It does not classify the
        # page before retrieval; it only prevents reference material from being
        # exported as if it were the requested item.
        if signal_count >= 2:
            return True
        if re.match(r"^(get|post|put|delete|patch)\b", title.strip(), flags=re.I):
            return True
        path = urlparse(url).path.casefold() if url else ""
        if any(part in path for part in ("/docs", "/documentation", "/api", "/sdk", "/pricing", "/faq")) and signal_count >= 1:
            return True
        return False

    def _requires_freshness(self, text: str) -> bool:
        return bool(re.search(r"\b(latest|today|current|breaking|recent|newest|now)\b|最新|今日|本日|速報|現在", str(text or ""), flags=re.I))

    def _publication_time_satisfies_freshness(self, publication_time: str) -> bool:
        value = self._clean(publication_time).casefold()
        if not value:
            return False
        # Relative timestamps usually come from source metadata around current retrieval.
        if re.search(r"\b\d{1,2}\s*(minutes?|hours?)\s+ago\b|\b(today|just now)\b|今日|本日|\d{1,2}分前|\d{1,2}時間前", value, flags=re.I):
            return True
        today = date.today()
        accepted_dates = {today, today - timedelta(days=1)}
        parsed = self._parse_publication_date(value, default_year=today.year)
        return bool(parsed and parsed in accepted_dates)

    def _parse_publication_date(self, value: str, *, default_year: int) -> date | None:
        text = self._clean(value)
        candidates = [
            (r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", lambda m: date(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
            (r"(\d{4})年(\d{1,2})月(\d{1,2})日", lambda m: date(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
            (r"(\d{1,2})月(\d{1,2})日", lambda m: date(default_year, int(m.group(1)), int(m.group(2)))),
        ]
        for pattern, builder in candidates:
            match = re.search(pattern, text)
            if match:
                try:
                    return builder(match)
                except ValueError:
                    return None
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(text[:32], fmt).date()
            except ValueError:
                pass
        return None

    def _contract_text(self, *, state: dict[str, Any], materials: list[dict[str, Any]]) -> str:
        candidates: list[str] = []
        if isinstance(state, dict):
            for key in ("original_input", "input", "user_message", "message"):
                value = state.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value)
            execution = state.get("execution") if isinstance(state.get("execution"), dict) else {}
            evidence = execution.get("evidence") if isinstance(execution.get("evidence"), dict) else {}
            value = evidence.get("original_user_input")
            if isinstance(value, str) and value.strip():
                candidates.append(value)
        for material in materials:
            if isinstance(material, dict):
                evidence = material.get("evidence") if isinstance(material.get("evidence"), dict) else {}
                value = evidence.get("original_user_input")
                if isinstance(value, str) and value.strip():
                    candidates.append(value)
        return "\n".join(dict.fromkeys(candidates))

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
                for key in ("search_results", "source_cards", "items", "results", "evidence_pack", "extracted_content_records", "selected_evidence_blocks", "selected_evidence"):
                    child = value.get(key)
                    if isinstance(child, list):
                        for record in child[:40]:
                            if isinstance(record, dict):
                                add_item(record, fallback_source=fallback_source or value)
                # Fetched/search documents may contain several source-backed items
                # in one visible text block. Split only by generic time markers and
                # preserve the original source URL as provenance.
                for derived in self._items_from_text_record(value, fallback_source=fallback_source):
                    add_item(derived, fallback_source=fallback_source or value)
                # Fetched document can also be represented as a single source item.
                if self._looks_like_public_source_record(value):
                    add_item(value, fallback_source=fallback_source)
                for key in ("data", "content", "result", "document", "evidence", "search", "web_search", "source_search_result", "optimized_evidence", "fetched_documents", "source_documents"):
                    child = value.get(key)
                    if isinstance(child, (dict, list)):
                        visit(child, fallback_source=fallback_source or value, depth=depth + 1)
            elif isinstance(value, list):
                for item in value[:80]:
                    visit(item, fallback_source=fallback_source, depth=depth + 1)

        visit(materials)
        return raw_items

    def _items_from_text_record(self, record: dict[str, Any], *, fallback_source: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        extracted_facts = record.get("extracted_facts") if isinstance(record.get("extracted_facts"), list) else []
        text = self._clean(
            record.get("evidence_excerpt") or record.get("text_excerpt") or record.get("visible_text_excerpt") or
            record.get("text") or record.get("snippet") or record.get("summary") or record.get("description") or
            " ".join(str(x) for x in extracted_facts[:8])
        )
        if len(text) < 80:
            return []
        url = self._clean(record.get("url") or record.get("source_url") or record.get("link") or (fallback_source or {}).get("url") or (fallback_source or {}).get("source_url"))
        source = self._clean(record.get("source") or record.get("publisher") or record.get("site_name") or record.get("source_name") or record.get("source_title") or record.get("title") or (fallback_source or {}).get("source_title") or (fallback_source or {}).get("title"))
        if not source and url:
            source = self._domain_from_url(url)
        time_pattern = re.compile(
            r"(\b\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?\b|"
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b|"
            r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{4}(?:\s*-\s*\d{1,2}:\d{2}\s*(?:AM|PM)?)?\b|"
            r"\b\d{1,2}\s*(?:minutes?|hours?|days?|weeks?)\s+ago\b|"
            r"\b(?:today|yesterday)\b|"
            r"\d{1,2}月\d{1,2}日(?:\s*\d{1,2}:\d{2})?|"
            r"\d{4}年\d{1,2}月\d{1,2}日(?:\s*\d{1,2}:\d{2})?)",
            flags=re.I,
        )
        matches = list(time_pattern.finditer(text))[:20]
        if not matches:
            return []
        items: list[dict[str, Any]] = []
        for idx, match in enumerate(matches):
            start = max(0, match.start() - 220)
            end = min(len(text), match.end() + 360)
            prev_end = matches[idx - 1].end() if idx > 0 else 0
            next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            start = max(start, prev_end)
            end = min(end, next_start)
            window = self._clean(text[start:end])
            before = self._clean(text[max(prev_end, match.start() - 180):match.start()])
            after = self._clean(text[match.end():min(next_start, match.end() + 260)])
            title_seed = before or after or window
            # Remove generic separators around source-list snippets without
            # depending on a concrete domain or topic.
            title_seed = re.split(r"\b(?:More|By|Advertisement|Share|Follow)\b", title_seed, flags=re.I)[-1].strip() or title_seed
            title = self._derive_title(title_seed)[:180]
            summary = window[:420]
            if not title or len(title) < 6:
                title = self._derive_title(after or window)[:180]
            if not title:
                continue
            items.append({
                "title": title,
                "summary": summary,
                "brief_summary": summary,
                "source": source,
                "publication_time": self._clean(match.group(0)),
                "url": url,
            })
        return items

    def _item_from_record(self, record: dict[str, Any], *, fallback_source: dict[str, Any] | None = None) -> dict[str, Any]:
        fallback_source = fallback_source if isinstance(fallback_source, dict) else {}
        title = self._clean(record.get("title") or record.get("name") or record.get("source_title") or fallback_source.get("title"))
        summary = self._clean(record.get("summary") or record.get("snippet") or record.get("description") or record.get("text") or record.get("text_excerpt") or record.get("visible_text_excerpt"))
        url = self._clean(record.get("url") or record.get("source_url") or record.get("link") or fallback_source.get("url") or fallback_source.get("source_url"))
        source = self._clean(record.get("source") or record.get("publisher") or record.get("site_name") or record.get("source_name") or record.get("domain") or record.get("source_title"))
        publication_time = self._clean(
            record.get("publication_time") or record.get("published_at") or record.get("published") or record.get("date") or record.get("time") or record.get("time_expression") or record.get("datetime")
        )
        if not publication_time:
            publication_time = self._derive_publication_time(" ".join(str(x or "") for x in [record.get("title"), record.get("summary"), record.get("snippet"), record.get("description"), record.get("text"), record.get("text_excerpt"), record.get("visible_text_excerpt")]))
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
            key = (str(item.get("url") or "") + "|" + str(item.get("title") or "")).casefold().strip("|").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _fetched_urls(self, materials: list[dict[str, Any]]) -> set[str]:
        urls: set[str] = set()
        def visit(value: Any, depth: int = 0) -> None:
            if depth > 7:
                return
            if isinstance(value, dict):
                status = str(value.get("status") or "").casefold()
                url = self._clean(value.get("url") or value.get("source_url") or value.get("link"))
                if url and (status in {"success", "available"} or value.get("response_status")):
                    urls.add(url)
                for key in ("fetched_documents", "source_documents", "documents", "document", "content", "data", "evidence"):
                    child = value.get(key)
                    if isinstance(child, (dict, list)):
                        visit(child, depth + 1)
            elif isinstance(value, list):
                for child in value[:120]:
                    visit(child, depth + 1)
        visit(materials)
        return urls

    def _item_has_fetched_url(self, item: dict[str, Any], fetched_urls: set[str]) -> bool:
        candidates = {self._clean(item.get("url") or "")}
        for value in item.get("supporting_urls") or []:
            if value:
                candidates.add(self._clean(value))
        candidates.discard("")
        return bool(candidates & fetched_urls)

    def _apply_consistency_gate(self, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Annotate and filter internally conflicting duplicated source items.

        The gate is generic: it does not know the topic. It groups items by a
        normalized title signature, compares repeated material from different
        URLs/sources, and rejects only groups that contain obvious internal
        conflicts in stable numeric/date-like claims. Single-source items remain
        usable but are marked as single-source; multi-source items keep their
        supporting source count for downstream verification/presentation.
        """
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            key = self._claim_key(item)
            if not key:
                key = self._clean(str(item.get("url") or item.get("title") or "")).casefold()
            groups.setdefault(key, []).append(item)
        kept: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for key, group in groups.items():
            urls = sorted({str(x.get("url") or "") for x in group if x.get("url")})
            sources = sorted({str(x.get("source") or "") for x in group if x.get("source")})
            signatures = [self._stable_claim_signature(x) for x in group]
            non_empty_signatures = [x for x in signatures if x]
            conflict = False
            if len(non_empty_signatures) >= 2:
                first = non_empty_signatures[0]
                # A conflict is only declared when two records about the same
                # claim key expose different stable numeric/date-like claims.
                conflict = any(sig != first for sig in non_empty_signatures[1:])
            if conflict:
                rejected.append({"claim_key": key, "reason": "conflicting_stable_claims", "sources": sources, "urls": urls})
                continue
            best = sorted(group, key=lambda x: (len(str(x.get("brief_summary") or x.get("summary") or "")), len(str(x.get("publication_time") or ""))), reverse=True)[0]
            best = dict(best)
            best["supporting_source_count"] = max(1, len(urls or sources))
            best["consistency_status"] = "cross_source_consistent" if len(urls or sources) > 1 else "single_source_verified"
            if urls:
                best["supporting_urls"] = urls[:8]
            kept.append(best)
        return kept, {"checked_groups": len(groups), "rejected_groups": rejected, "kept_count": len(kept)}

    def _claim_key(self, item: dict[str, Any]) -> str:
        title = self._clean(item.get("title") or "").casefold()
        if not title:
            return ""
        title = re.sub(r"https?://\S+", "", title)
        title = re.sub(r"[^\w\s぀-ヿ㐀-鿿]+", " ", title)
        tokens = [t for t in title.split() if len(t) > 1]
        return " ".join(tokens[:16])

    def _stable_claim_signature(self, item: dict[str, Any]) -> tuple[str, ...]:
        text = self._clean(" ".join(str(item.get(k) or "") for k in ("title", "brief_summary", "summary")))
        values = re.findall(r"\d+(?:\.\d+)?\s*(?:%|percent|人|名|円|ドル|usd|km|m|cm|℃|度)?", text, flags=re.I)
        # Dates inside publication_time are source metadata, not the factual
        # claim being compared, so only compare claim text values.
        return tuple(sorted(dict.fromkeys(v.casefold() for v in values)))

    def _rank_items_for_fields(self, items: list[dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
        required = [self._canonical_field(f) for f in fields if f not in {"brief", "for_each_story", "for_each_item"}]
        def score(item: dict[str, Any]) -> tuple[int, int]:
            present = 0
            for field in required:
                if field == "brief_summary":
                    ok = bool(item.get("brief_summary") or item.get("summary"))
                elif field == "publication_time":
                    ok = bool(item.get("publication_time"))
                else:
                    ok = bool(item.get(field))
                present += 1 if ok else 0
            text_len = len(str(item.get("brief_summary") or item.get("summary") or ""))
            return (present, min(text_len, 500))
        return sorted(items, key=score, reverse=True)

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
                method = str(value.get("execution_method") or value.get("execution_mode") or value.get("method") or value.get("prompt_profile") or value.get("capability") or "").casefold()
                capability = str(value.get("capability") or "").casefold()
                if method in {"web_search", "web_query", "source_retrieval", "web_retrieval"} or capability == "web_retrieval":
                    return True
                if any(isinstance(value.get(key), list) for key in ("results", "search_results", "source_cards", "fetched_documents", "source_documents")):
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

    def _contract_from_state_text(self, *, state: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, Any]:
        text_candidates: list[str] = []
        if isinstance(state, dict):
            for key in ("original_input", "input", "user_message", "message"):
                value = state.get(key)
                if isinstance(value, str) and value.strip():
                    text_candidates.append(value)
            execution = state.get("execution") if isinstance(state.get("execution"), dict) else {}
            evidence = execution.get("evidence") if isinstance(execution.get("evidence"), dict) else {}
            value = evidence.get("original_user_input")
            if isinstance(value, str) and value.strip():
                text_candidates.append(value)
        for material in materials:
            if isinstance(material, dict):
                evidence = material.get("evidence") if isinstance(material.get("evidence"), dict) else {}
                value = evidence.get("original_user_input")
                if isinstance(value, str) and value.strip():
                    text_candidates.append(value)
        text = "\n".join(dict.fromkeys(text_candidates))
        if not text.strip():
            return {}
        fields = self._requested_fields_from_text(text)
        requested = self._requested_count_from_text(text)
        requires_source = bool(fields and self._contains_source_field(fields)) or bool(re.search(r"\b(source|sources|url|link|published|publication|citation|reference|evidence)\b", text, flags=re.I))
        contract: dict[str, Any] = {}
        if requires_source:
            contract["requires_source_material"] = True
        if fields:
            contract["requested_output_fields"] = fields
        if requested > 0:
            contract["output_cardinality"] = {"mode": "exact", "requested_count": requested}
        return contract

    def _requested_fields_from_text(self, text: str) -> list[str]:
        canonical_known = {"title", "brief_summary", "summary", "source", "url", "link", "publication_time", "published_at", "published_time", "time", "date"}
        fields: list[str] = []
        for line in str(text or "").splitlines():
            raw = line.strip().strip("-•* ").strip()
            if not raw or len(raw) > 80:
                continue
            raw = raw.strip(":：")
            normalized = self._normalize_field(raw)
            canonical = self._canonical_field(normalized)
            if normalized in canonical_known or canonical in {"title", "brief_summary", "source", "url", "publication_time"}:
                if canonical not in fields:
                    fields.append(canonical)
        return fields

    def _requested_count_from_text(self, text: str) -> int:
        match = re.search(r"\b(\d{1,2})\b", str(text or ""))
        if not match:
            return 0
        try:
            value = int(match.group(1))
        except Exception:
            return 0
        return value if 0 < value <= 20 else 0

    def _derive_publication_time(self, text: str) -> str:
        sample = self._clean(text)[:1600]
        if not sample:
            return ""
        patterns = (
            r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?\b",
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
            r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
            r"\b\d{1,2}\s*(?:minutes?|hours?|days?|weeks?)\s+ago\b",
            r"\b(?:today|yesterday)\b",
            r"\d{1,2}月\d{1,2}日(?:\s*\d{1,2}:\d{2})?",
            r"\d{4}年\d{1,2}月\d{1,2}日(?:\s*\d{1,2}:\d{2})?",
        )
        for pattern in patterns:
            match = re.search(pattern, sample, flags=re.I)
            if match:
                return match.group(0).strip()
        return ""

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

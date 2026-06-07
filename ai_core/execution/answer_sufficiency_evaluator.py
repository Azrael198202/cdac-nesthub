from __future__ import annotations

import math
import re
import unicodedata
from typing import Any


class RuntimeSemanticSignalEvaluator:
    """Language-neutral semantic signal scorer for answer evidence.

    This evaluator intentionally avoids fixed English stop-word lists and
    domain-specific answer keywords. It relies on runtime variables, entity and
    temporal coverage, factual density, and query/evidence lexical overlap using
    unicode-aware tokenization.
    """

    GENERIC_DOC_PATH_HINTS = ("/api", "/docs", "/developer", "/developers", "/reference")
    GENERIC_DOC_TITLE_HINTS = ("api", "sdk", "docs", "documentation", "developer", "reference")

    def extract_query_terms(self, *, user_input: str, objective: str | None, capability: str | None, known: dict[str, Any]) -> list[str]:
        # Prefer the runtime step objective over a large transport/envelope
        # message.  The envelope can contain many orchestration words that are
        # unrelated to the actual evidence need and can otherwise dominate
        # semantic scoring.
        objective_text = str(objective or "").strip()
        capability_text = str(capability or "").strip()
        raw = " ".join(x for x in [objective_text, capability_text] if x)
        if not raw:
            raw = self._extract_embedded_objective(str(user_input or "")) or str(user_input or "")
        for value in self._flatten_values(known):
            raw = raw.replace(str(value), " ")
        return self._dedupe_keep_order(self._tokens(raw))[:16]

    def _extract_embedded_objective(self, text: str) -> str:
        match = re.search(r'"objective"\s*:\s*"([^"]+)"', str(text or ""), flags=re.I)
        return match.group(1) if match else ""

    def _flatten_values(self, value: Any) -> list[Any]:
        values: list[Any] = []
        def add(v: Any) -> None:
            if isinstance(v, dict):
                for x in v.values():
                    add(x)
            elif isinstance(v, (list, tuple, set)):
                for x in v:
                    add(x)
            elif v is not None and str(v).strip():
                values.append(v)
        add(value)
        return values

    def semantic_signal(self, text: str, query_terms: list[str]) -> float:
        hay = self._normalize(text)
        if not hay:
            return 0.0
        lexical = self._lexical_overlap(hay, query_terms)
        factual = self.factual_density(hay)
        structure = self.answer_structure_signal(hay)
        # Use max rather than requiring English keywords. A table of numbers or
        # dates can be high-signal even when query words are translated.
        return max(lexical, factual * 0.85, structure * 0.75)

    def factual_density(self, text: str) -> float:
        if not text:
            return 0.0
        # Generic factual patterns: numbers with units/symbols, ISO-like dates,
        # time, percentages, ranges, coordinates, and table-like repeated values.
        patterns = [
            r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b",
            r"\b\d{1,2}[-/.]\d{1,2}\b",
            r"\b\d{1,2}:\d{2}\b",
            r"\b\d+(?:\.\d+)?\s?(?:°|%|km|mm|cm|m|kg|g|mph|kph|hpa|pa|usd|jpy|eur|gbp|cny)\b",
            r"\b\d+(?:\.\d+)?\s?[~-]\s?\d+(?:\.\d+)?\b",
            r"\b\d+(?:\.\d+)?\b",
        ]
        hits = 0
        for pattern in patterns:
            hits += len(re.findall(pattern, text, flags=re.IGNORECASE))
        return min(1.0, hits / 10.0)

    def answer_structure_signal(self, text: str) -> float:
        if not text:
            return 0.0
        # Generic evidence shapes: key-value lines, tables/lists, repeated date
        # rows, or enough compact text with factual density.
        key_value = len(re.findall(r"[^\n:]{2,40}\s*[:：]\s*[^\n]{1,80}", text))
        rows = len([line for line in text.splitlines() if len(line.strip()) > 8])
        score = min(1.0, (key_value / 5.0) + (rows / 30.0))
        return score

    def looks_like_reference_document(self, *, text: str, url: str | None = None, title: str | None = None) -> bool:
        hay = self._normalize(" ".join(x for x in [title or "", url or "", text[:1000]] if x))
        if not hay:
            return False
        path_hit = any(hint in hay for hint in self.GENERIC_DOC_PATH_HINTS)
        title_hit = any(re.search(rf"\b{re.escape(hint)}\b", hay) for hint in self.GENERIC_DOC_TITLE_HINTS)
        # Treat as reference documentation only when there are integration-like
        # signals and weak factual answer density.
        return bool((path_hit or title_hit) and self.factual_density(text) < 0.25)

    def _lexical_overlap(self, normalized_text: str, query_terms: list[str]) -> float:
        if not query_terms:
            return 0.5 if len(normalized_text) > 160 else 0.0
        terms = [self._normalize(t) for t in query_terms if t]
        if not terms:
            return 0.0
        hits = 0
        for term in terms[:8]:
            if len(term) >= 2 and term in normalized_text:
                hits += 1
        return min(1.0, hits / max(1, min(len(terms), 5)))

    def _tokens(self, text: str) -> list[str]:
        normalized = self._normalize(text)
        # Latin/number tokens plus CJK runs. No stop-word list: low-information
        # terms naturally have low impact because they also need evidence density
        # and runtime variable coverage.
        tokens = re.findall(r"[\w+-]{2,}|[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]{1,}", normalized, flags=re.UNICODE)
        return [t for t in tokens if len(t.strip()) >= 2]

    def _normalize(self, text: str) -> str:
        return unicodedata.normalize("NFKC", str(text or "")).casefold()

    def _dedupe_keep_order(self, items: list[str]) -> list[str]:
        seen = set()
        out = []
        for item in items:
            if item not in seen:
                out.append(item)
                seen.add(item)
        return out


class AnswerSufficiencyEvaluator:
    """Decide whether generic web evidence can answer the user's request.

    This gate is provider-neutral, domain-neutral, and language-aware. It
    prevents ordinary answer lookups from falling through into API documentation
    search or runtime code generation when collected evidence covers the runtime
    variables and contains factual answer material.
    """

    DEFAULT_MIN_COVERAGE = 1.0
    DEFAULT_MIN_SCORE = 0.72
    MAX_SELECTED = 7
    FETCHABLE_MIN_SCORE = 0.45

    def __init__(self, semantic_evaluator: RuntimeSemanticSignalEvaluator | None = None) -> None:
        self.semantic = semantic_evaluator or RuntimeSemanticSignalEvaluator()

    def evaluate(
        self,
        *,
        user_input: str,
        objective: str | None,
        capability: str | None,
        known_parameters: dict[str, Any],
        evidence: list[dict[str, Any]],
        min_score: float | None = None,
    ) -> dict[str, Any]:
        min_score = self.DEFAULT_MIN_SCORE if min_score is None else min_score
        known = self._clean_known(known_parameters)
        semantic_terms = self.semantic.extract_query_terms(
            user_input=user_input,
            objective=objective,
            capability=capability,
            known=known,
        )

        scored: list[dict[str, Any]] = []
        aggregate_text_parts: list[str] = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            text = self._evidence_text(item)
            if not text:
                continue
            aggregate_text_parts.append(text)
            coverage = self._coverage(text, known)
            answer_signal = self.semantic.semantic_signal(text, semantic_terms)
            pub = self._public_evidence(item, {"score": 0, "coverage": coverage, "answer_signal": answer_signal})
            reference_penalty = 0.25 if self.semantic.looks_like_reference_document(text=text, url=pub.get("url"), title=pub.get("title")) and coverage["coverage_ratio"] < 1.0 else 0.0
            score = (coverage["coverage_ratio"] * 0.68) + (answer_signal * 0.32) - reference_penalty
            scored.append({
                "score": round(max(0.0, min(1.0, score)), 3),
                "coverage": coverage,
                "answer_signal": round(answer_signal, 3),
                "reference_document_like": self.semantic.looks_like_reference_document(text=text, url=pub.get("url"), title=pub.get("title")),
                "item": item,
                "text_preview": text[:1200],
            })

        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        aggregate_text = "\n".join(aggregate_text_parts)
        aggregate_coverage = self._coverage(aggregate_text, known)
        aggregate_answer_signal = self.semantic.semantic_signal(aggregate_text, semantic_terms)
        best_score = float(scored[0]["score"]) if scored else 0.0
        aggregate_score = (aggregate_coverage["coverage_ratio"] * 0.68) + (aggregate_answer_signal * 0.32)
        effective_score = max(best_score, aggregate_score)
        fetch_candidates = [x for x in scored if self._needs_fetch(x)]
        passed = bool(
            scored
            and aggregate_coverage["passed"]
            and effective_score >= min_score
            and aggregate_answer_signal > 0
            and not self._aggregate_is_only_search_snippets(scored)
        )

        selected = [
            self._public_evidence(x["item"], x)
            for x in scored[: self.MAX_SELECTED]
            if x.get("score", 0) >= self.FETCHABLE_MIN_SCORE
        ]
        if passed:
            reason = "sufficient_web_answer_evidence"
            next_action = "direct_answer"
        elif fetch_candidates:
            reason = "promising_search_results_need_page_fetch"
            next_action = "fetch_selected_pages"
        else:
            reason = "insufficient_web_answer_evidence"
            next_action = "continue_api_or_tool_discovery"
        return {
            "passed": passed,
            "score": round(effective_score, 3),
            "min_score": min_score,
            "aggregate_coverage": aggregate_coverage,
            "aggregate_answer_signal": round(aggregate_answer_signal, 3),
            "semantic_signal_terms": semantic_terms,
            "selected_evidence": selected,
            "fetch_candidate_count": len(fetch_candidates),
            "evidence_count": len(evidence),
            "scored_count": len(scored),
            "reason": reason,
            "next_action": next_action,
        }

    def _clean_known(self, known: dict[str, Any]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        if not isinstance(known, dict):
            return output
        for key, value in known.items():
            if key in {"context", "source_step", "parameters", "known", "optional"}:
                continue
            if value is None or value == "":
                continue
            if isinstance(value, (str, int, float, bool)):
                output[str(key)] = value
            elif isinstance(value, (list, tuple, set)):
                compact = [x for x in value if isinstance(x, (str, int, float, bool)) and str(x).strip()]
                if compact:
                    output[str(key)] = compact
            elif isinstance(value, dict):
                compact_dict: dict[str, Any] = {}
                for child_key, child_value in value.items():
                    if isinstance(child_value, (str, int, float, bool)) and str(child_value).strip():
                        compact_dict[str(child_key)] = child_value
                    elif isinstance(child_value, (list, tuple, set)):
                        child_list = [x for x in child_value if isinstance(x, (str, int, float, bool)) and str(x).strip()]
                        if child_list:
                            compact_dict[str(child_key)] = child_list
                if compact_dict:
                    output[str(key)] = compact_dict
        return output

    def _evidence_text(self, item: dict[str, Any]) -> str:
        parts: list[str] = []
        containers = [item]
        for nested_key in ("document", "source_search_result", "evidence"):
            nested = item.get(nested_key) if isinstance(item.get(nested_key), dict) else None
            if nested:
                containers.append(nested)
                for sub_key in ("document", "source_search_result"):
                    sub = nested.get(sub_key) if isinstance(nested.get(sub_key), dict) else None
                    if sub:
                        containers.append(sub)
        for container in containers:
            for key in (
                "title", "name", "snippet", "description", "text_excerpt",
                "visible_text_excerpt", "html_excerpt", "dom_evidence_text",
                "url", "official_documentation_url",
            ):
                value = container.get(key) if isinstance(container, dict) else None
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
            dom_items = container.get("dom_evidence_items") if isinstance(container, dict) else None
            if isinstance(dom_items, list):
                for entry in dom_items[:120]:
                    if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                        parts.append(entry.get("text", ""))
        return "\n".join(parts)

    def _coverage(self, text: str, known: dict[str, Any]) -> dict[str, Any]:
        if not known:
            return {"passed": True, "coverage_ratio": 1.0, "matched": {}, "missing": [], "partial": {}}
        hay = self._normalize(text)
        matched: dict[str, list[str]] = {}
        partial: dict[str, list[str]] = {}
        missing: list[str] = []
        considered = 0
        for key, value in known.items():
            if key in {"detail_level", "semantic_modifiers", "specificity"}:
                continue
            considered += 1
            variants = self._variants(value)
            hits = [v for v in variants if v and v in hay]
            if hits:
                matched[key] = hits[:5]
                continue
            partial_hits = [v for v in self._partial_variants(value) if v and v in hay]
            if partial_hits:
                partial[key] = partial_hits[:5]
            else:
                missing.append(key)
        ratio = 1.0 if considered == 0 else ((len(matched) + 0.5 * len(partial)) / considered)
        return {"passed": not missing and not partial, "coverage_ratio": round(ratio, 3), "matched": matched, "missing": missing, "partial": partial}

    def _variants(self, value: Any) -> list[str]:
        variants: list[str] = []
        if isinstance(value, dict):
            for x in value.values():
                variants.extend(self._variants(x))
            return [v for v in dict.fromkeys(variants) if v]
        if isinstance(value, (list, tuple, set)):
            for x in value:
                variants.extend(self._variants(x))
            return [v for v in dict.fromkeys(variants) if v]
        raw = self._normalize(str(value).strip())
        variants = [raw]
        if "," in raw:
            variants.extend([x.strip() for x in raw.split(",") if x.strip()])
        if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
            y, m, d = raw[:4], raw[5:7], raw[8:10]
            try:
                mi = int(m)
                di = int(d)
                month_names = {1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "jun", 7: "jul", 8: "aug", 9: "sep", 10: "oct", 11: "nov", 12: "dec"}
                month_full = {1: "january", 2: "february", 3: "march", 4: "april", 5: "may", 6: "june", 7: "july", 8: "august", 9: "september", 10: "october", 11: "november", 12: "december"}
                mon = month_names.get(mi, "")
                full = month_full.get(mi, "")
                variants.extend([
                    f"{y}/{m}/{d}", f"{y}.{m}.{d}", f"{m}/{d}", f"{m}-{d}", f"{mi}/{di}", f"{mi}-{di}",
                    f"{full} {di}" if full else "", f"{mon} {di}" if mon else "",
                    f"{di} {full}" if full else "", f"{di} {mon}" if mon else "",
                    f"{di}",
                ])
            except Exception:
                pass
        return [v for v in dict.fromkeys(variants) if v]

    def _partial_variants(self, value: Any) -> list[str]:
        variants: list[str] = []
        if isinstance(value, dict):
            for x in value.values():
                variants.extend(self._partial_variants(x))
            return [v for v in dict.fromkeys(variants) if v]
        if isinstance(value, (list, tuple, set)):
            for x in value:
                variants.extend(self._partial_variants(x))
            return [v for v in dict.fromkeys(variants) if v]
        raw = self._normalize(str(value).strip())
        if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
            y, m = raw[:4], raw[5:7]
            try:
                mi = int(m)
                month_full = {1: "january", 2: "february", 3: "march", 4: "april", 5: "may", 6: "june", 7: "july", 8: "august", 9: "september", 10: "october", 11: "november", 12: "december"}
                full = month_full.get(mi, "")
                variants.extend([f"{full} {y}" if full else "", f"{y}-{m}", f"{y}/{m}", full])
            except Exception:
                pass
        return [v for v in dict.fromkeys(variants) if v]

    def _needs_fetch(self, scored: dict[str, Any]) -> bool:
        if scored.get("score", 0) < self.FETCHABLE_MIN_SCORE:
            return False
        item = scored.get("item") if isinstance(scored.get("item"), dict) else {}
        text_excerpt = ""
        for container in (item, item.get("document") if isinstance(item.get("document"), dict) else {}, item.get("evidence") if isinstance(item.get("evidence"), dict) else {}):
            if isinstance(container, dict) and isinstance(container.get("text_excerpt"), str):
                text_excerpt += container.get("text_excerpt", "")
        url = self._public_evidence(item, scored).get("url")
        return bool(url) and len(text_excerpt.strip()) < 400

    def _aggregate_is_only_search_snippets(self, scored: list[dict[str, Any]]) -> bool:
        if not scored:
            return False
        considered = scored[: self.MAX_SELECTED]
        fetched_or_body_count = 0
        for entry in considered:
            item = entry.get("item") if isinstance(entry.get("item"), dict) else {}
            if self._has_fetched_body(item):
                fetched_or_body_count += 1
        return fetched_or_body_count == 0

    def _has_fetched_body(self, value: Any, *, depth: int = 0) -> bool:
        if depth > 4 or not isinstance(value, dict):
            return False
        if isinstance(value.get("document"), dict):
            return True
        body = ""
        for key in ("text_excerpt", "visible_text_excerpt", "html_excerpt", "dom_evidence_text"):
            if isinstance(value.get(key), str):
                body += value.get(key, "")
        if len(body.strip()) >= 120:
            return True
        for nested_key in ("evidence", "source_search_result", "document"):
            nested = value.get(nested_key)
            if isinstance(nested, dict) and self._has_fetched_body(nested, depth=depth + 1):
                return True
        return False

    def _public_evidence(self, item: dict[str, Any], scored: dict[str, Any]) -> dict[str, Any]:
        doc = item.get("document") if isinstance(item.get("document"), dict) else {}
        search = item.get("source_search_result") if isinstance(item.get("source_search_result"), dict) else {}
        url = item.get("url") or doc.get("url") or search.get("url")
        title = item.get("title") or doc.get("title") or search.get("title")
        snippet = item.get("snippet") or search.get("snippet") or doc.get("text_excerpt", "")[:500]
        return {
            "url": url,
            "title": title,
            "snippet": snippet,
            "score": scored.get("score"),
            "coverage": scored.get("coverage"),
            "answer_signal": scored.get("answer_signal"),
            "source": item.get("source") or "web_answer_evidence",
            "evidence": item,
        }

    def _normalize(self, text: str) -> str:
        return unicodedata.normalize("NFKC", str(text or "")).casefold()

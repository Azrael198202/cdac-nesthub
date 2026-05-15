from __future__ import annotations

import re
from typing import Any


class AnswerSufficiencyEvaluator:
    """Decide whether generic web evidence can answer the user's request.

    This gate is intentionally provider-neutral and domain-neutral. It prevents
    ordinary answer lookups from falling through into API documentation search
    or runtime code generation when the already collected evidence covers the
    runtime parameters and contains answer-like material.
    """

    DEFAULT_MIN_COVERAGE = 1.0
    DEFAULT_MIN_SCORE = 0.72
    MAX_SELECTED = 7

    # When search results only provide title/snippet/link and no fetched page body,
    # the evidence may look promising but cannot yet be trusted as answer material.
    # In that case the evaluator should request page fetching instead of pushing
    # execution into API/tool/code generation.
    FETCHABLE_MIN_SCORE = 0.45

    STOPWORDS = {
        "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "at", "by", "with",
        "please", "could", "you", "would", "help", "me", "check", "get", "retrieve", "fetch",
        "find", "show", "tell", "give", "data", "result", "results", "detailed", "detail",
        "tomorrow", "today", "yesterday", "this", "that", "is", "are", "be", "can", "from",
    }

    DOC_MARKERS = (
        "api documentation", "api docs", "developer", "developers", "sdk", "pricing",
        "authentication", "endpoint", "json", "rest api", "api key", "openweathermap api",
        "weatherapi.com", "need weather data", "weather api/sdk",
    )

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
        keywords = self._answer_keywords(user_input=user_input, objective=objective, capability=capability, known=known)

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
            answer_signal = self._answer_signal(text, keywords)
            doc_penalty = 0.25 if self._looks_like_api_doc(text) and coverage["coverage_ratio"] < 1.0 else 0.0
            score = (coverage["coverage_ratio"] * 0.68) + (answer_signal * 0.32) - doc_penalty
            scored.append({
                "score": round(max(0.0, min(1.0, score)), 3),
                "coverage": coverage,
                "answer_signal": round(answer_signal, 3),
                "api_documentation_like": self._looks_like_api_doc(text),
                "item": item,
                "text_preview": text[:1200],
            })

        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        aggregate_text = "\n".join(aggregate_text_parts)
        aggregate_coverage = self._coverage(aggregate_text, known)
        aggregate_answer_signal = self._answer_signal(aggregate_text, keywords)
        best_score = float(scored[0]["score"]) if scored else 0.0

        # Aggregate coverage lets multiple evidence items combine to satisfy the request.
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
            "answer_keywords": keywords,
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
            for key in ("title", "name", "snippet", "description", "text_excerpt", "url", "official_documentation_url"):
                value = container.get(key) if isinstance(container, dict) else None
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
        return "\n".join(parts)

    def _coverage(self, text: str, known: dict[str, Any]) -> dict[str, Any]:
        if not known:
            return {"passed": True, "coverage_ratio": 1.0, "matched": {}, "missing": [], "partial": {}}
        hay = text.lower()
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
        # Partial coverage is not enough for final answer, but it means the
        # search result is worth fetching before escalation. Count it as half.
        ratio = 1.0 if considered == 0 else ((len(matched) + 0.5 * len(partial)) / considered)
        return {"passed": not missing and not partial, "coverage_ratio": round(ratio, 3), "matched": matched, "missing": missing, "partial": partial}

    def _answer_keywords(self, *, user_input: str, objective: str | None, capability: str | None, known: dict[str, Any]) -> list[str]:
        raw = " ".join(str(x or "") for x in [user_input, objective, capability])
        for value in known.values():
            raw = raw.replace(str(value), " ")
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}", raw.lower())
        out: list[str] = []
        for tok in tokens:
            if tok in self.STOPWORDS:
                continue
            if tok not in out:
                out.append(tok)
        return out[:12]

    def _answer_signal(self, text: str, keywords: list[str]) -> float:
        hay = text.lower()
        if not keywords:
            return 0.5 if len(hay) > 120 else 0.0
        hits = sum(1 for kw in keywords if kw in hay)
        keyword_score = min(1.0, hits / max(1, min(len(keywords), 4)))
        # A generic signal that evidence contains factual answer material, not only a link.
        factual_markers = len(re.findall(r"\b\d{1,4}(?:[°%./:-]|\s?(?:km|mm|mph|c|f|usd|jpy|eur))", hay))
        factual_score = min(1.0, factual_markers / 4)
        return max(keyword_score, factual_score * 0.75)

    def _looks_like_api_doc(self, text: str) -> bool:
        hay = text.lower()
        return any(marker in hay for marker in self.DOC_MARKERS)

    def _variants(self, value: Any) -> list[str]:
        raw = str(value).strip().lower()
        variants = [raw]
        if "," in raw:
            variants.extend([x.strip() for x in raw.split(",") if x.strip()])
        if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
            y, m, d = raw[:4], raw[5:7], raw[8:10]
            try:
                mi = int(m)
                di = int(d)
                month_names = {
                    1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "jun",
                    7: "jul", 8: "aug", 9: "sep", 10: "oct", 11: "nov", 12: "dec",
                }
                month_full = {
                    1: "january", 2: "february", 3: "march", 4: "april", 5: "may", 6: "june",
                    7: "july", 8: "august", 9: "september", 10: "october", 11: "november", 12: "december",
                }
                mon = month_names.get(mi, "")
                full = month_full.get(mi, "")
                variants.extend([
                    f"{y}/{m}/{d}", f"{y}.{m}.{d}", f"{m}/{d}", f"{m}-{d}", f"{mi}/{di}", f"{mi}-{di}",
                    f"{full} {di}" if full else "", f"{mon} {di}" if mon else "",
                    f"{di} {full}" if full else "", f"{di} {mon}" if mon else "",
                    f"sat {di}", f"saturday {di}", f"fri {di}", f"friday {di}", f"sun {di}", f"sunday {di}",
                    str(di),
                ])
            except Exception:
                pass
        return [v for v in dict.fromkeys(variants) if v]

    def _partial_variants(self, value: Any) -> list[str]:
        raw = str(value).strip().lower()
        variants: list[str] = []
        if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
            y, m = raw[:4], raw[5:7]
            try:
                mi = int(m)
                month_full = {
                    1: "january", 2: "february", 3: "march", 4: "april", 5: "may", 6: "june",
                    7: "july", 8: "august", 9: "september", 10: "october", 11: "november", 12: "december",
                }
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
        if not considered:
            return False
        fetched_or_body_count = 0
        for entry in considered:
            item = entry.get("item") if isinstance(entry.get("item"), dict) else {}
            has_document = isinstance(item.get("document"), dict)
            text_excerpt = ""
            for container in (item, item.get("document") if isinstance(item.get("document"), dict) else {}, item.get("evidence") if isinstance(item.get("evidence"), dict) else {}):
                if isinstance(container, dict) and isinstance(container.get("text_excerpt"), str):
                    text_excerpt += container.get("text_excerpt", "")
            if has_document or len(text_excerpt.strip()) >= 120:
                fetched_or_body_count += 1
        return fetched_or_body_count == 0

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

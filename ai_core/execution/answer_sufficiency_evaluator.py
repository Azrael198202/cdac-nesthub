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
    MAX_SELECTED = 5

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
        passed = bool(
            scored
            and aggregate_coverage["passed"]
            and max(best_score, aggregate_score) >= min_score
            and aggregate_answer_signal > 0
        )

        selected = [self._public_evidence(x["item"], x) for x in scored[: self.MAX_SELECTED] if x.get("score", 0) >= 0.45]
        return {
            "passed": passed,
            "score": round(max(best_score, aggregate_score), 3),
            "min_score": min_score,
            "aggregate_coverage": aggregate_coverage,
            "aggregate_answer_signal": round(aggregate_answer_signal, 3),
            "answer_keywords": keywords,
            "selected_evidence": selected,
            "evidence_count": len(evidence),
            "scored_count": len(scored),
            "reason": "sufficient_web_answer_evidence" if passed else "insufficient_web_answer_evidence",
            "next_action": "direct_answer" if passed else "continue_api_or_tool_discovery",
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
            return {"passed": True, "coverage_ratio": 1.0, "matched": {}, "missing": []}
        hay = text.lower()
        matched: dict[str, list[str]] = {}
        missing: list[str] = []
        considered = 0
        for key, value in known.items():
            if key in {"detail_level", "semantic_modifiers"}:
                continue
            considered += 1
            variants = self._variants(value)
            hits = [v for v in variants if v and v in hay]
            if hits:
                matched[key] = hits[:5]
            else:
                missing.append(key)
        ratio = 1.0 if considered == 0 else (len(matched) / considered)
        return {"passed": not missing, "coverage_ratio": round(ratio, 3), "matched": matched, "missing": missing}

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
                variants.extend([
                    f"{y}/{m}/{d}", f"{y}.{m}.{d}", f"{m}/{d}", f"{m}-{d}", f"{mi}/{di}", f"{mi}-{di}", str(di),
                    f"may {di}" if mi == 5 else "", f"{di} may" if mi == 5 else "",
                ])
            except Exception:
                pass
        return [v for v in dict.fromkeys(variants) if v]

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

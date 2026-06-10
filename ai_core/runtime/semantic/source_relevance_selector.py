from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class SourceRelevanceDecision:
    title: str
    url: str
    text: str
    score: float
    matched_terms: tuple[str, ...]
    kept: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["matched_terms"] = list(self.matched_terms)
        return data


class SourceRelevanceSelector:
    """Select source cards that are actually relevant to the user request.

    This is a domain-neutral grounding gate.  It does not know any product,
    library, database, vendor, or business word.  It only compares the user's
    requested terms with each candidate source text and returns up to
    ``max_sources`` cards that pass a relevance threshold.  Final synthesis must
    use these selected cards, not the raw top-N search results.
    """

    TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+.#/-]+|[\u3040-\u30ff\u3400-\u9fff]+")
    STOP_WORDS = {
        "the", "and", "for", "with", "from", "that", "this", "please", "using", "about",
        "what", "which", "when", "where", "how", "does", "into", "only", "give", "show",
        "latest", "newest", "current", "stable", "official", "source", "sources", "citation",
        "citations", "reference", "references", "verify", "verified", "version", "versions",
        "update", "updated", "release", "released", "information", "answer", "final",
        "について", "ください", "お願いします", "查询", "搜索", "信息", "内容", "最新", "稳定", "版本", "引用", "来源",
    }
    META_TERMS = {
        "latest", "newest", "current", "stable", "official", "version", "versions", "release", "released",
        "verify", "verified", "source", "sources", "citation", "reference", "最新", "稳定", "版本", "来源", "引用",
    }

    def select(
        self,
        *,
        user_input: str,
        source_cards: list[dict[str, Any]],
        max_sources: int = 5,
        min_score: float = 0.28,
    ) -> dict[str, Any]:
        query_terms = self._query_terms(user_input, include_meta=False)
        meta_terms = self._query_terms(user_input, include_meta=True, only_meta=True)
        decisions: list[SourceRelevanceDecision] = []
        seen_urls: set[str] = set()
        selected: list[dict[str, Any]] = []

        for raw_card in source_cards:
            card = self._normalize_card(raw_card)
            url = card.get("url", "")
            key = url or (card.get("title", "") + card.get("text", "")[:80])
            if key in seen_urls:
                continue
            seen_urls.add(key)
            score, matched = self._score(card=card, query_terms=query_terms, meta_terms=meta_terms)
            kept = score >= min_score
            reason = "query_relevant" if kept else "low_query_relevance"
            decisions.append(SourceRelevanceDecision(
                title=card.get("title", ""),
                url=url,
                text=card.get("text", ""),
                score=round(score, 4),
                matched_terms=tuple(matched),
                kept=kept,
                reason=reason,
            ))
            if kept:
                selected.append({**card, "relevance_score": round(score, 4), "matched_terms": matched})

        selected.sort(key=lambda item: (float(item.get("relevance_score") or 0.0), self._has_numeric_signal(item)), reverse=True)
        selected = selected[:max_sources]
        selected_urls = {str(item.get("url") or "") for item in selected}
        for idx, decision in enumerate(decisions):
            if decision.url in selected_urls:
                decisions[idx] = SourceRelevanceDecision(
                    title=decision.title,
                    url=decision.url,
                    text=decision.text,
                    score=decision.score,
                    matched_terms=decision.matched_terms,
                    kept=True,
                    reason="selected_relevant_source",
                )
        return {
            "selected_sources": selected,
            "selected_urls": [str(item.get("url") or "") for item in selected if str(item.get("url") or "").startswith("http")],
            "decisions": [decision.to_dict() for decision in decisions],
            "query_terms": query_terms,
            "meta_terms": meta_terms,
            "passed": bool(selected),
            "max_sources": max_sources,
            "min_score": min_score,
        }

    def _normalize_card(self, card: Any) -> dict[str, str]:
        if not isinstance(card, dict):
            return {"title": "", "url": "", "text": ""}
        return {
            "title": " ".join(str(card.get("title") or card.get("url") or "source").split())[:240],
            "url": str(card.get("url") or "").strip()[:500],
            "text": " ".join(str(card.get("text") or card.get("snippet") or card.get("text_excerpt") or card.get("visible_text_excerpt") or "").split())[:1800],
        }

    def _score(self, *, card: dict[str, str], query_terms: list[str], meta_terms: list[str]) -> tuple[float, list[str]]:
        haystack = (card.get("title", "") + " " + card.get("text", "") + " " + card.get("url", "")).casefold()
        if not haystack.strip():
            return 0.0, []
        matched: list[str] = []
        for term in query_terms:
            if term and term.casefold() in haystack and term not in matched:
                matched.append(term)
        if not query_terms:
            base = 0.0
        else:
            base = len(matched) / max(1, len(query_terms))
        anchor_bonus = 0.0
        if matched:
            title = card.get("title", "").casefold()
            url = card.get("url", "").casefold()
            anchor_bonus += min(0.22, 0.06 * sum(1 for term in matched if term.casefold() in title or term.casefold() in url))
        meta_bonus = 0.0
        if meta_terms:
            meta_hits = [term for term in meta_terms if term.casefold() in haystack]
            meta_bonus = min(0.16, 0.04 * len(meta_hits))
        numeric_bonus = 0.08 if self._has_numeric_signal(card) else 0.0
        return min(1.0, base + anchor_bonus + meta_bonus + numeric_bonus), matched

    def _query_terms(self, text: str, *, include_meta: bool, only_meta: bool = False) -> list[str]:
        raw_terms = [m.group(0).casefold() for m in self.TOKEN_PATTERN.finditer(str(text or ""))]
        out: list[str] = []
        for term in raw_terms:
            clean = term.strip(" .,:;()[]{}<>\"'`")
            if len(clean) < 2:
                continue
            is_meta = clean in self.META_TERMS
            if only_meta and not is_meta:
                continue
            if not include_meta and clean in self.STOP_WORDS:
                continue
            if clean not in out:
                out.append(clean)
            if len(out) >= 24:
                break
        return out

    def _has_numeric_signal(self, card: dict[str, str]) -> int:
        text = card.get("title", "") + " " + card.get("text", "")
        return 1 if re.search(r"\d", text) else 0

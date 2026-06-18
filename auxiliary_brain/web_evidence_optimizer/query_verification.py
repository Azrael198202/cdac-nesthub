from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueryVerificationResult:
    passed: bool
    query: str
    original_query: str
    reasons: list[str]
    rewrite_applied: bool
    intent_profile: dict[str, Any]


class SearchQueryVerificationGate:
    """Verify that a retrieval query still matches the user's evidence intent.

    The gate is domain-neutral.  It checks generic intent features such as
    content-vs-tool intent, freshness, requested item fields, and whether core
    user terms survived query planning.  It can rewrite an invalid query from
    the original step instruction before retrieval starts.
    """

    TOOL_REFERENCE_TERMS = {
        "api", "apis", "sdk", "documentation", "docs", "developer", "endpoint", "endpoints",
        "library", "libraries", "package", "packages", "github", "pricing", "quota", "authentication",
        "reference", "tutorial", "quickstart", "quick", "start", "examples", "example",
    }
    CONTENT_REQUEST_TERMS = {
        "news", "story", "stories", "article", "articles", "report", "reports", "event", "events",
        "forecast", "weather", "price", "prices", "market", "markets", "data", "information", "summary",
        "summaries", "source", "sources", "publication", "published", "time", "today", "latest",
        "current", "recent", "breaking", "headline", "headlines",
    }
    FRESHNESS_TERMS = {"latest", "today", "current", "recent", "breaking", "newest", "now", "今日", "本日", "最新", "速報", "現在"}
    STOPWORDS = {
        "please", "provide", "show", "tell", "give", "find", "search", "lookup", "look", "call",
        "for", "each", "with", "from", "this", "that", "the", "and", "or", "of", "to", "in", "on",
        "a", "an", "is", "are", "was", "were", "be", "get", "use", "using", "must", "should",
        "title", "brief", "summary", "source", "publication", "time", "url", "link", "story", "stories",
        "item", "items", "today", "latest", "current", "recent", "breaking", "news",
        "parameters", "agent", "step", "final_answer", "answer",
    }

    def verify_and_rewrite(self, *, query: str, user_input: str, objective: str = "", source_contract: dict[str, Any] | None = None) -> dict[str, Any]:
        original_query = " ".join(str(query or "").split())
        text = "\n".join(x for x in [str(user_input or ""), str(objective or "")] if x).strip()
        contract = source_contract if isinstance(source_contract, dict) else {}
        profile = self._intent_profile(text=text, source_contract=contract)
        reasons = self._failure_reasons(query=original_query, profile=profile)
        if not reasons:
            return QueryVerificationResult(True, original_query, original_query, [], False, profile).__dict__
        rewritten = self._rewrite_query(text=text, profile=profile, fallback=original_query)
        second_reasons = self._failure_reasons(query=rewritten, profile=profile)
        # Do not keep self-referential tool/reference queries for content requests.
        passed = not second_reasons or (set(second_reasons) <= {"query_missing_some_core_terms"})
        return QueryVerificationResult(
            passed=passed,
            query=rewritten if rewritten else original_query,
            original_query=original_query,
            reasons=reasons,
            rewrite_applied=bool(rewritten and rewritten != original_query),
            intent_profile=profile,
        ).__dict__

    def _intent_profile(self, *, text: str, source_contract: dict[str, Any]) -> dict[str, Any]:
        lower = text.casefold()
        fields = source_contract.get("requested_output_fields") if isinstance(source_contract.get("requested_output_fields"), list) else []
        field_text = " ".join(str(x) for x in fields).casefold()
        content_score = sum(1 for t in self.CONTENT_REQUEST_TERMS if re.search(rf"\b{re.escape(t)}\b", lower))
        tool_score = sum(1 for t in self.TOOL_REFERENCE_TERMS if re.search(rf"\b{re.escape(t)}\b", lower))
        wants_source_items = bool(fields) or bool(re.search(r"\b\d+\s+(?:items?|stories|articles|results|sources?)\b", lower))
        wants_content = content_score > 0 or wants_source_items or bool(source_contract.get("requires_source_material"))
        explicit_tool_request = tool_score > 0 and bool(re.search(r"\b(api|sdk|documentation|docs|library|package|endpoint|implementation|code|developer)\b", lower))
        freshness_required = any(term in lower for term in self.FRESHNESS_TERMS)
        core_terms = self._core_terms(text)
        # Preserve target terms from contract hints when present.
        for value in [source_contract.get("target"), source_contract.get("topic"), source_contract.get("location")]:
            if isinstance(value, str):
                for term in self._core_terms(value):
                    if term not in core_terms:
                        core_terms.append(term)
        return {
            "wants_content": wants_content,
            "explicit_tool_request": explicit_tool_request,
            "freshness_required": freshness_required,
            "requested_fields": fields,
            "field_text": field_text,
            "core_terms": core_terms[:10],
            "original_text": text,
        }

    def _failure_reasons(self, *, query: str, profile: dict[str, Any]) -> list[str]:
        q = str(query or "").strip()
        lower = q.casefold()
        reasons: list[str] = []
        if not q:
            reasons.append("query_empty")
            return reasons
        tool_hits = [t for t in self.TOOL_REFERENCE_TERMS if re.search(rf"\b{re.escape(t)}\b", lower)]
        if profile.get("explicit_tool_request"):
            return []
        if profile.get("wants_content") and tool_hits:
            content_hits = [t for t in self.CONTENT_REQUEST_TERMS if re.search(rf"\b{re.escape(t)}\b", lower)]
            if len(tool_hits) >= max(1, len(content_hits)):
                reasons.append("query_targets_tool_or_reference_material_not_requested_content")
        if profile.get("freshness_required") and not any(term in lower for term in self.FRESHNESS_TERMS):
            reasons.append("query_missing_freshness_intent")
        core_terms = [str(x).casefold() for x in profile.get("core_terms") or [] if str(x).strip()]
        if core_terms:
            hits = [term for term in core_terms if term in lower]
            if not hits:
                reasons.append("query_missing_core_terms")
            elif len(hits) < min(2, len(core_terms)) and len(core_terms) > 1:
                reasons.append("query_missing_some_core_terms")
        return reasons

    def _rewrite_query(self, *, text: str, profile: dict[str, Any], fallback: str) -> str:
        terms: list[str] = []
        for term in profile.get("core_terms") or []:
            if term and term not in terms:
                terms.append(str(term))
        lower = str(text or "").casefold()
        if profile.get("freshness_required"):
            # Preserve the user's generic freshness intent without assuming a domain.
            if "latest" not in terms and "最新" not in lower:
                terms.insert(0, "latest")
            if "today" in lower and "today" not in terms:
                terms.append("today")
            elif "今日" in lower and "今日" not in terms:
                terms.append("今日")
        # Preserve evidence/output nature when the request asks for source items.
        if profile.get("wants_content") and not any(t in {"news", "articles", "stories", "sources", "weather", "forecast"} for t in terms):
            for token in ("news", "articles", "sources"):
                if token in lower and token not in terms:
                    terms.append(token)
        if not terms:
            terms = self._core_terms(text) or self._core_terms(fallback)
        # Remove accidental tool/reference routing unless explicitly requested.
        if profile.get("wants_content") and not profile.get("explicit_tool_request"):
            terms = [t for t in terms if t.casefold() not in self.TOOL_REFERENCE_TERMS]
        return " ".join(terms[:12]).strip() or fallback

    def _core_terms(self, text: str) -> list[str]:
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_+./:-]{1,60}|[\u3040-\u30ff\u3400-\u9fff]{2,}", str(text or ""))
        out: list[str] = []
        for token in tokens:
            clean = token.strip(" .,:;()[]{}<>\\\"'`")
            low = clean.casefold()
            if not clean or low in self.STOPWORDS or low in self.TOOL_REFERENCE_TERMS:
                continue
            if re.match(r"^step\d+$", low):
                continue
            if clean not in out:
                out.append(clean)
            if len(out) >= 14:
                break
        return out

from __future__ import annotations

import re
from typing import Any


class AnswerQualityGate:
    """Generic final-answer quality gate.

    The gate prevents raw source dumps, empty citation-only answers, and answers
    without verified structured material from passing as successful synthesis.
    """

    URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

    def evaluate(self, *, answer: str, answer_plan: dict[str, Any] | None = None, resolved_claims: dict[str, Any] | None = None) -> dict[str, Any]:
        text = str(answer or "").strip()
        plan = answer_plan if isinstance(answer_plan, dict) else {}
        claims = resolved_claims if isinstance(resolved_claims, dict) else {}
        facts = claims.get("facts") if isinstance(claims.get("facts"), list) else []
        if not text:
            return {"passed": False, "reason": "empty_answer"}
        url_count = len(self.URL_RE.findall(text))
        non_url_text = self.URL_RE.sub("", text).strip()
        if url_count and len(non_url_text) < 80:
            return {"passed": False, "reason": "source_list_without_answer", "url_count": url_count}
        if plan.get("status") == "insufficient" and not facts:
            return {"passed": False, "reason": "insufficient_verified_facts"}
        if "Most relevant extracted text fields" in text:
            return {"passed": False, "reason": "raw_extraction_dump"}
        if text.count("http://") + text.count("https://") >= 3 and len(non_url_text) < 240:
            return {"passed": False, "reason": "citation_dump"}
        return {"passed": True, "reason": "passed", "url_count": url_count, "fact_count": len(facts)}

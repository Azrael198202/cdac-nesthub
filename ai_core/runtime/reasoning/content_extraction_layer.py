from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse


class ContentExtractionLayer:
    """Extract compact, source-bound content records from fetched pages.

    This layer is domain-neutral. It does not know website names or business
    entities. It converts page text, DOM evidence items, and link-like records
    into generic source records that later reasoning layers can normalize into
    facts.
    """

    DATE_OR_TIME = re.compile(
        r"(\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*(?:AM|PM)\b|"
        r"\b(?:today|yesterday|updated|published|posted)\b|"
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b|"
        r"\b\d{1,2}\s*(?:minutes?|hours?|days?)\s+ago\b|"
        r"\b\d{1,2}月\d{1,2}日\b|\b\d{1,2}時\d{0,2}分?\b)",
        re.IGNORECASE,
    )
    URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)

    def extract(self, *, fetched_documents: list[dict[str, Any]], max_records: int = 40) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for doc in fetched_documents:
            if not isinstance(doc, dict):
                continue
            base_url = str(doc.get("url") or doc.get("source_url") or "").strip()
            title = self._clean(str(doc.get("title") or ""))
            for item in self._records_from_dom_items(doc, base_url=base_url, page_title=title):
                key = self._record_key(item)
                if key and key not in seen:
                    seen.add(key)
                    records.append(item)
                    if len(records) >= max_records:
                        return records
            for item in self._records_from_text_blocks(doc, base_url=base_url, page_title=title):
                key = self._record_key(item)
                if key and key not in seen:
                    seen.add(key)
                    records.append(item)
                    if len(records) >= max_records:
                        return records
        return records

    def _records_from_dom_items(self, doc: dict[str, Any], *, base_url: str, page_title: str) -> list[dict[str, Any]]:
        items = doc.get("dom_evidence_items") if isinstance(doc.get("dom_evidence_items"), list) else []
        out: list[dict[str, Any]] = []
        for item in items[:240]:
            if not isinstance(item, dict):
                continue
            raw = self._clean(str(item.get("text") or ""))
            if not self._looks_like_content(raw):
                continue
            url = self._first_url(raw) or base_url
            out.append({
                "kind": "extracted_content_record",
                "title": self._compact_title(raw, page_title=page_title),
                "text": raw[:900],
                "url": self._absolute_url(url, base_url),
                "source_url": base_url,
                "source_title": page_title,
                "time_expression": self._first_time(raw),
                "relevance_score": self._content_score(raw),
            })
        return out

    def _records_from_text_blocks(self, doc: dict[str, Any], *, base_url: str, page_title: str) -> list[dict[str, Any]]:
        text = self._clean(" ".join(str(doc.get(k) or "") for k in ("text_excerpt", "visible_text_excerpt", "html_excerpt", "dom_evidence_text")))
        if not text:
            return []
        chunks = re.split(r"(?<=[.!?。！？])\s+|\s{2,}|\n+", text)
        out: list[dict[str, Any]] = []
        window: list[str] = []
        for chunk in chunks[:500]:
            clean = self._clean(chunk)
            if not clean:
                continue
            window.append(clean)
            if len(window) > 3:
                window.pop(0)
            candidate = self._clean(" ".join(window))
            if not self._looks_like_content(candidate):
                continue
            out.append({
                "kind": "extracted_content_record",
                "title": self._compact_title(candidate, page_title=page_title),
                "text": candidate[:900],
                "url": base_url,
                "source_url": base_url,
                "source_title": page_title,
                "time_expression": self._first_time(candidate),
                "relevance_score": self._content_score(candidate),
            })
            if len(out) >= 24:
                break
        return out

    def _looks_like_content(self, text: str) -> bool:
        if len(text) < 28:
            return False
        words = text.split()
        if len(words) < 4 and not re.search(r"[。！？]", text):
            return False
        if len(text) > 1200:
            return False
        nav_terms = {"privacy", "cookies", "subscribe", "advertisement", "sign in", "menu", "copyright"}
        lower = text.casefold()
        if any(term in lower for term in nav_terms) and len(words) < 10:
            return False
        return True

    def _content_score(self, text: str) -> float:
        score = 0.35
        if self.DATE_OR_TIME.search(text):
            score += 0.25
        if self.URL_RE.search(text):
            score += 0.1
        if 50 <= len(text) <= 500:
            score += 0.15
        if re.search(r"\d", text):
            score += 0.05
        return min(score, 0.95)

    def _compact_title(self, text: str, *, page_title: str) -> str:
        clean = self._clean(text)
        parts = re.split(r"(?<=[.!?。！？])\s+|\s[-|–—]\s", clean)
        title = self._clean(parts[0] if parts else clean)
        if len(title) > 160:
            title = title[:157].rstrip() + "..."
        return title or page_title

    def _first_time(self, text: str) -> str:
        match = self.DATE_OR_TIME.search(text or "")
        return match.group(0) if match else ""

    def _first_url(self, text: str) -> str:
        match = self.URL_RE.search(text or "")
        return match.group(0).rstrip(".,;") if match else ""

    def _absolute_url(self, url: str, base_url: str) -> str:
        if not url:
            return base_url
        try:
            if urlparse(url).scheme in {"http", "https"}:
                return url
            return urljoin(base_url, url)
        except Exception:
            return base_url

    def _record_key(self, item: dict[str, Any]) -> str:
        return (str(item.get("url") or "") + "|" + str(item.get("title") or "")[:120]).casefold()

    def _clean(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

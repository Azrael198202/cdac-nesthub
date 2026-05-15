from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from ai_core.config.paths import RUNTIME_TRACES
from ai_core.utils.safe_json import safe_json_dumps


@dataclass
class WebResearchResult:
    status: str
    query: str = ""
    url: str = ""
    title: str = ""
    snippet: str = ""
    text_excerpt: str = ""
    response_status: int | None = None
    error: str = ""
    fetched_at: str = ""


class GenericWebResearchTool:
    """Generic web research capability for runtime discovery.

    This is allowed in core because it is domain-neutral infrastructure. It
    never chooses a domain-specific provider or connector. It only performs
    generic search/fetch/extract work and writes evidence traces for runtime
    intelligence to consume.
    """

    def __init__(self) -> None:
        self.trace_dir = RUNTIME_TRACES / "web_research"
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    async def search(self, *, query: str, max_results: int = 5, timeout_seconds: float = 20.0) -> dict[str, Any]:
        """Best-effort generic web search using public HTML search pages.

        The exact search provider is not a business API connector; it is a
        generic discovery mechanism. Failure is returned as structured data so
        the runtime can escalate to an external model with web-search support.
        """
        query = str(query or "").strip()
        if not query:
            return self._record("search", {"status": "error", "error": "query is required", "results": []})

        # DuckDuckGo HTML endpoint is intentionally generic and requires no key.
        # If blocked/unavailable, runtime can escalate through model route.
        url = "https://duckduckgo.com/html/?q=" + quote_plus(query)
        results: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, headers={"User-Agent": "AI-Core-Runtime/1.0"}) as client:
                response = await client.get(url)
                response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for item in soup.select(".result")[:max_results]:
                a = item.select_one(".result__a")
                snippet = item.select_one(".result__snippet")
                href = a.get("href") if a else ""
                results.append(asdict(WebResearchResult(
                    status="success",
                    query=query,
                    url=self._normalize_search_url(str(href or "")),
                    title=self._clean(a.get_text(" ") if a else ""),
                    snippet=self._clean(snippet.get_text(" ") if snippet else ""),
                    response_status=response.status_code,
                    fetched_at=self._now(),
                )))
            return self._record("search", {"status": "success", "query": query, "search_url": url, "results": results})
        except Exception as exc:
            return self._record("search", {"status": "error", "query": query, "search_url": url, "error": str(exc), "results": results})

    async def fetch(self, *, url: str, timeout_seconds: float = 20.0, max_chars: int = 8000) -> dict[str, Any]:
        url = str(url or "").strip()
        if not self._safe_http_url(url):
            return self._record("fetch", {"status": "error", "url": url, "error": "Only http/https URLs are allowed."})
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, headers={"User-Agent": "AI-Core-Runtime/1.0"}) as client:
                response = await client.get(url)
                response.raise_for_status()
            raw_html = response.text or ""
            soup = BeautifulSoup(raw_html, "html.parser")
            title = self._clean(soup.title.get_text(" ") if soup.title else "")

            dom_items = self._extract_dom_evidence_items(soup, limit=260)
            dom_text = self._clean(" ".join(item.get("text", "") for item in dom_items))[:max_chars]
            html_excerpt = self._extract_html_excerpt(raw_html, max_chars=max_chars)

            text_soup = BeautifulSoup(raw_html, "html.parser")
            for tag in text_soup(["script", "style", "noscript"]):
                tag.decompose()
            visible_text = self._clean(text_soup.get_text(" "))[:max_chars]
            # v70.16: some useful evidence appears only in DOM attributes
            # (title/alt/aria-label/data-*), including structured page cards. Include
            # an attribute-derived excerpt so sufficiency checks can match dates
            # and factual values without depending on rendered text only.
            combined_text = self._clean(" ".join([visible_text, dom_text]))[:max_chars]
            return self._record("fetch", {
                "status": "success",
                "url": url,
                "response_status": response.status_code,
                "title": title,
                "text_excerpt": combined_text,
                "visible_text_excerpt": visible_text,
                "html_excerpt": html_excerpt,
                "dom_evidence_text": dom_text,
                "dom_evidence_items": dom_items[:80],
                "fetched_at": self._now(),
            })
        except Exception as exc:
            return self._record("fetch", {"status": "error", "url": url, "error": str(exc), "fetched_at": self._now()})

    def _extract_html_excerpt(self, raw_html: str, *, max_chars: int = 8000) -> str:
        """Return a compact, attribute-preserving HTML evidence excerpt.

        This is intentionally generic. It keeps tags/attributes that often carry
        factual evidence in modern pages (structured cards, icon alt/title, link
        title, data-* attributes) while dropping script/style noise.
        """
        try:
            soup = BeautifulSoup(raw_html or "", "html.parser")
            for tag in soup(["script", "style", "noscript", "svg"]):
                tag.decompose()
            chunks: list[str] = []
            useful_attrs = {"title", "alt", "aria-label", "datetime", "href", "src"}
            for tag in soup.find_all(True):
                attrs: list[str] = []
                for key, value in (tag.attrs or {}).items():
                    if key in useful_attrs or key.startswith("data-"):
                        if isinstance(value, (list, tuple)):
                            value = " ".join(str(v) for v in value)
                        cleaned = self._clean(str(value))
                        if cleaned:
                            attrs.append(f'{key}="{cleaned[:160]}"')
                text = self._clean(tag.get_text(" ", strip=True))
                if attrs or text:
                    chunks.append(f"<{tag.name} {' '.join(attrs)}> {text[:240]}")
                if sum(len(c) for c in chunks) > max_chars * 1.2:
                    break
            return self._clean(" ".join(chunks))[:max_chars]
        except Exception:
            return self._clean(raw_html or "")[:max_chars]

    def _extract_dom_evidence_items(self, soup: BeautifulSoup, *, limit: int = 200) -> list[dict[str, Any]]:
        """Extract generic DOM evidence from text and useful attributes.

        The extractor is not tied to any specific domain or website. It captures
        repeated cards/table cells/list items and attribute values that can carry
        structured facts, such as dates, labels, icons, and numeric values.
        """
        items: list[dict[str, Any]] = []
        useful_attrs = ("title", "alt", "aria-label", "datetime", "href")
        for tag in soup.find_all(["a", "td", "th", "tr", "li", "div", "span", "img"]):
            values: list[str] = []
            text = self._clean(tag.get_text(" ", strip=True))
            if text:
                values.append(text)
            for attr in useful_attrs:
                value = tag.get(attr)
                if isinstance(value, (list, tuple)):
                    value = " ".join(str(v) for v in value)
                if value:
                    values.append(self._clean(str(value)))
            for key, value in (tag.attrs or {}).items():
                if key.startswith("data-"):
                    if isinstance(value, (list, tuple)):
                        value = " ".join(str(v) for v in value)
                    if value:
                        values.append(f"{key}={self._clean(str(value))}")
            joined = self._clean(" ".join(v for v in values if v))
            # Keep compact factual/label-bearing items. Pure navigation noise is
            # naturally filtered by requiring either a digit, a degree/percent, or
            # multiple semantic tokens.
            if not joined:
                continue
            if not (re.search(r"\d|°|%", joined) or len(joined.split()) >= 3):
                continue
            items.append({
                "tag": tag.name,
                "text": joined[:500],
                "class": " ".join(tag.get("class") or [])[:160] if tag.get("class") else "",
            })
            if len(items) >= limit:
                break
        return items

    def _record(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        trace_id = f"{kind}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        path = self.trace_dir / f"{trace_id}.json"
        record = {
            "trace_id": trace_id,
            "kind": kind,
            "created_at": self._now(),
            "payload": payload,
            "trace_path": str(path),
        }
        path.write_text(safe_json_dumps(record, indent=2), encoding="utf-8")
        payload["web_research_trace"] = {"trace_id": trace_id, "trace_path": str(path)}
        return payload

    def _normalize_search_url(self, href: str) -> str:
        href = str(href or "").strip()
        if not href:
            return ""
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"}:
            return href
        query = parse_qs(parsed.query)
        for key in ("uddg", "url", "u"):
            value = query.get(key)
            if value:
                candidate = unquote(value[0])
                if self._safe_http_url(candidate):
                    return candidate
        if href.startswith("//"):
            return "https:" + href
        return href

    def _safe_http_url(self, value: str) -> bool:
        try:
            parsed = urlparse(value)
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False

    def _clean(self, value: str) -> str:
        value = html.unescape(str(value or ""))
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

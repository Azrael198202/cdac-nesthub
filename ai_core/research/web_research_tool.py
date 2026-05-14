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
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            title = self._clean(soup.title.get_text(" ") if soup.title else "")
            text = self._clean(soup.get_text(" "))[:max_chars]
            return self._record("fetch", {
                "status": "success",
                "url": url,
                "response_status": response.status_code,
                "title": title,
                "text_excerpt": text,
                "fetched_at": self._now(),
            })
        except Exception as exc:
            return self._record("fetch", {"status": "error", "url": url, "error": str(exc), "fetched_at": self._now()})

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

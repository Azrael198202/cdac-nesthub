from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from ai_core.config.paths import RUNTIME_TRACES
from ai_core.utils.safe_json import safe_json_dumps
from auxiliary_brain.research.source_retrieval_settings import SourceRetrievalSettingsStore


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
        self.source_settings = SourceRetrievalSettingsStore()

    async def search(self, *, query: str, max_results: int = 5, timeout_seconds: float = 20.0, engine_id: str | None = None) -> dict[str, Any]:
        """Best-effort generic web search with structured evidence output.

        URL discovery is explicit and provider-backed. The default provider is a
        no-key DuckDuckGo HTML search page. Optional API providers can be enabled
        through environment variables without changing ai_core logic:
        - AI_CORE_WEB_SEARCH_PROVIDER=duckduckgo_html|bing_api|google_custom_search|auto
        - BING_SEARCH_ENDPOINT and BING_SEARCH_API_KEY for Bing Web Search
        - GOOGLE_CSE_ID and GOOGLE_API_KEY for Google Custom Search JSON API
        The returned contract always includes provider_config, attempts,
        candidate URLs, and normalized results for downstream verification.
        """
        query = str(query or "").strip()
        if not query:
            return self._record("search", {"status": "error", "error": "query is required", "results": [], "attempts": [], "provider_config": self._provider_config([])})

        direct_url = query if self._safe_http_url(query) else ""
        if direct_url:
            return self._record("search", {
                "status": "success",
                "query": query,
                "search_strategy": "direct_url",
                "search_url": direct_url,
                "provider_config": self._provider_config([{"provider": "direct_url", "kind": "direct"}]),
                "results": [asdict(WebResearchResult(status="success", query=query, url=direct_url, title=direct_url, fetched_at=self._now()))],
                "attempts": [{"provider": "direct_url", "kind": "direct", "status": "success", "url": direct_url}],
            })

        providers = self._search_provider_specs(query, engine_id=engine_id)
        results: list[dict[str, Any]] = []
        attempts: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        headers = self._http_headers()
        per_attempt_timeout = max(3.0, float(timeout_seconds) / max(len(providers), 1))
        async with httpx.AsyncClient(timeout=per_attempt_timeout, follow_redirects=True, headers=headers) as client:
            for spec in providers:
                provider_name = str(spec.get("provider") or "search_provider")
                url = str(spec.get("url") or "")
                kind = str(spec.get("kind") or "html")
                try:
                    req_headers = dict(headers)
                    req_headers.update(spec.get("headers") if isinstance(spec.get("headers"), dict) else {})
                    response = await client.get(url, headers=req_headers)
                    response.raise_for_status()
                    if kind == "bing_json":
                        extracted = self._extract_bing_json_results(response.json(), query=query, response_status=response.status_code, max_results=max_results)
                    elif kind == "google_json":
                        extracted = self._extract_google_json_results(response.json(), query=query, response_status=response.status_code, max_results=max_results)
                    else:
                        extracted = self._extract_search_results(
                            html_text=response.text or "",
                            query=query,
                            response_status=response.status_code,
                            max_results=max_results,
                            base_url=url,
                            provider_name=provider_name,
                        )
                    kept = 0
                    for item in extracted:
                        item_url = str(item.get("url") or "").strip()
                        if not item_url or item_url in seen_urls or not self._safe_http_url(item_url):
                            continue
                        seen_urls.add(item_url)
                        item["discovered_by"] = provider_name
                        results.append(item)
                        kept += 1
                        if len(results) >= max_results:
                            break
                    attempts.append({"provider": provider_name, "kind": kind, "status": "success", "url": url, "kept_results": kept, "response_status": response.status_code})
                    if len(results) >= max_results:
                        break
                except Exception as exc:
                    attempts.append({"provider": provider_name, "kind": kind, "status": "error", "url": url, "error": str(exc)})

        status = "success" if results else "error"
        payload: dict[str, Any] = {
            "status": status,
            "query": query,
            "search_strategy": "search_engine",
            "search_url": str(providers[0].get("url") or "") if providers else "",
            "provider_config": self._provider_config(providers),
            "results": results,
            "attempts": attempts,
        }
        if not results:
            payload["error"] = "no search results collected"
        return self._record("search", payload)

    def _search_provider_specs(self, query: str, engine_id: str | None = None) -> list[dict[str, Any]]:
        """Return configured search-engine providers.

        This is generic infrastructure, not business routing. DuckDuckGo HTML is
        the default no-key provider. Bing and Google are available only when the
        required environment configuration exists.
        """
        encoded = quote_plus(query)
        requested = str(engine_id or os.getenv("AI_CORE_WEB_SEARCH_PROVIDER") or "").strip().lower()
        providers: list[dict[str, Any]] = []

        def add_duckduckgo() -> None:
            providers.extend([
                {"provider": "duckduckgo_html", "engine_id": "duckduckgo", "kind": "html", "url": "https://duckduckgo.com/html/?q=" + encoded, "requires_key": False},
                {"provider": "duckduckgo_html_fallback", "engine_id": "duckduckgo", "kind": "html", "url": "https://html.duckduckgo.com/html/?q=" + encoded, "requires_key": False},
            ])

        def add_bing() -> None:
            endpoint = str(os.getenv("BING_SEARCH_ENDPOINT") or "").rstrip("/")
            key = str(os.getenv("BING_SEARCH_API_KEY") or "")
            if endpoint and key:
                providers.append({
                    "provider": "bing_api",
                    "engine_id": "bing",
                    "kind": "bing_json",
                    "url": endpoint + "/v7.0/search?q=" + encoded,
                    "headers": {"Ocp-Apim-Subscription-Key": key},
                    "requires_key": True,
                })
            providers.append({"provider": "bing_html", "engine_id": "bing", "kind": "html", "url": "https://www.bing.com/search?q=" + encoded, "requires_key": False})

        def add_google() -> None:
            cse_id = str(os.getenv("GOOGLE_CSE_ID") or "")
            api_key = str(os.getenv("GOOGLE_API_KEY") or "")
            if cse_id and api_key:
                providers.append({
                    "provider": "google_custom_search",
                    "engine_id": "google",
                    "kind": "google_json",
                    "url": "https://www.googleapis.com/customsearch/v1?key=" + quote_plus(api_key) + "&cx=" + quote_plus(cse_id) + "&q=" + encoded,
                    "requires_key": True,
                })
            providers.append({"provider": "google_html", "engine_id": "google", "kind": "html", "url": "https://www.google.com/search?q=" + encoded, "requires_key": False})

        def add_engine(engine: str) -> None:
            engine = str(engine or "").strip().lower()
            if engine in {"google", "google_custom_search", "google_cse"}:
                add_google()
            elif engine in {"bing", "bing_api"}:
                add_bing()
            elif engine in {"duckduckgo", "duckduckgo_html", "ddg"}:
                add_duckduckgo()

        if requested:
            add_engine(requested)
        else:
            for engine in self.source_settings.engine_order_for_execution():
                add_engine(engine)
        if not providers:
            add_google()
            add_bing()
            add_duckduckgo()
        return providers

    def _provider_config(self, providers: list[dict[str, Any]]) -> dict[str, Any]:
        names = []
        for spec in providers:
            name = str(spec.get("provider") or "").strip()
            if name and name not in names:
                names.append(name)
        settings = self.source_settings.load()
        return {
            "configured_provider": str(os.getenv("AI_CORE_WEB_SEARCH_PROVIDER") or "runtime_settings"),
            "routing_mode": settings.routing_mode,
            "configured_engine_order": settings.engine_order or ["google", "bing", "duckduckgo"],
            "active_provider_order": names,
            "default_provider": "google",
            "optional_providers": {
                "bing_api": bool(os.getenv("BING_SEARCH_ENDPOINT") and os.getenv("BING_SEARCH_API_KEY")),
                "google_custom_search": bool(os.getenv("GOOGLE_CSE_ID") and os.getenv("GOOGLE_API_KEY")),
                "google_html": True,
                "bing_html": True,
                "duckduckgo_html": True,
            },
            "url_discovery_method": "search_engine_or_direct_url",
        }

    def _extract_bing_json_results(self, payload: dict[str, Any], *, query: str, response_status: int, max_results: int) -> list[dict[str, Any]]:
        items = ((payload or {}).get("webPages") or {}).get("value") if isinstance(payload, dict) else []
        output: list[dict[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not self._safe_http_url(url):
                continue
            output.append(asdict(WebResearchResult(
                status="success",
                query=query,
                url=url,
                title=self._clean(str(item.get("name") or url))[:300],
                snippet=self._clean(str(item.get("snippet") or ""))[:600],
                response_status=response_status,
                fetched_at=self._now(),
            )))
            if len(output) >= max_results * 2:
                break
        return output

    def _extract_google_json_results(self, payload: dict[str, Any], *, query: str, response_status: int, max_results: int) -> list[dict[str, Any]]:
        items = (payload or {}).get("items") if isinstance(payload, dict) else []
        output: list[dict[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or "").strip()
            if not self._safe_http_url(url):
                continue
            output.append(asdict(WebResearchResult(
                status="success",
                query=query,
                url=url,
                title=self._clean(str(item.get("title") or url))[:300],
                snippet=self._clean(str(item.get("snippet") or ""))[:600],
                response_status=response_status,
                fetched_at=self._now(),
            )))
            if len(output) >= max_results * 2:
                break
        return output

    def _extract_search_results(self, *, html_text: str, query: str, response_status: int, max_results: int, base_url: str = "", provider_name: str = "") -> list[dict[str, Any]]:
        soup = BeautifulSoup(html_text or "", "html.parser")
        output: list[dict[str, Any]] = []

        containers = soup.select(".result, .web-result, article, li")
        if not containers:
            containers = list(soup.find_all("a"))

        for container in containers:
            anchor = container.select_one("a.result__a") if hasattr(container, "select_one") else None
            if anchor is None:
                anchor = container if getattr(container, "name", "") == "a" else container.find("a", href=True)
            if anchor is None or not anchor.get("href"):
                continue
            url = self._normalize_search_url(str(anchor.get("href") or ""), base_url=base_url)
            if not self._safe_http_url(url) or self._is_search_navigation_url(url):
                continue
            title = self._clean(anchor.get_text(" ") or anchor.get("title") or url)
            snippet_node = container.select_one(".result__snippet, .b_caption p, .snippet, p") if hasattr(container, "select_one") else None
            snippet = self._clean(snippet_node.get_text(" ") if snippet_node else container.get_text(" "))
            if not self._looks_like_search_result_item(url=url, title=title, snippet=snippet, provider_name=provider_name):
                continue
            if snippet == title:
                snippet = ""
            output.append(asdict(WebResearchResult(
                status="success",
                query=query,
                url=url,
                title=title[:300],
                snippet=snippet[:600],
                response_status=response_status,
                fetched_at=self._now(),
            )))
            if len(output) >= max_results * 2:
                break
        return output

    def _is_search_navigation_url(self, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.netloc or "").casefold()
        path = (parsed.path or "").casefold()
        query = (parsed.query or "").casefold()
        if not host:
            return True
        if "google." in host or host.startswith("support.google"):
            # Search result pages, JavaScript enable pages, support, account, and
            # retry URLs are provider/navigation material, not user evidence.
            if host.startswith("support.google") or path.startswith(("/search", "/httpservice/", "/preferences", "/settings", "/sorry", "/account", "/support", "/copilotsearch")):
                return True
            if host in {"www.google.com", "google.com"} and path in {"/", ""}:
                return True
        if "bing.com" in host:
            if path.startswith(("/search", "/copilotsearch", "/account", "/profile", "/images", "/videos", "/maps")):
                return True
            if path in {"/", ""} and ("form=" in query or not query):
                return True
        if "duckduckgo" in host and path in {"/", "/html/", "/lite/", "/settings"}:
            return True
        return path.startswith("/settings")

    def _looks_like_search_result_item(self, *, url: str, title: str, snippet: str, provider_name: str = "") -> bool:
        """Reject provider chrome while keeping generic public result cards.

        HTML search pages often include links such as "Enable JavaScript",
        "Search help", "Images", and account/navigation pages.  Those links
        are valid URLs but not source material.  This filter is deliberately
        provider-neutral: a candidate needs an external destination and either
        a meaningful title or snippet.
        """
        parsed = urlparse(url)
        host = (parsed.netloc or "").casefold()
        provider = str(provider_name or "").casefold()
        provider_hosts = {
            "google": ("google.", "gstatic.", "googleusercontent."),
            "bing": ("bing.com", "microsoft.com"),
            "duckduckgo": ("duckduckgo.com", "duck.co"),
        }
        for engine, fragments in provider_hosts.items():
            if engine in provider and any(fragment in host for fragment in fragments):
                return False
        compact = self._clean(" ".join([title, snippet]))
        if len(compact) < 8:
            return False
        bad_titles = {"all", "search", "images", "videos", "maps", "news", "shopping", "feedback", "settings", "tools", "here", "click here"}
        if compact.casefold() in bad_titles:
            return False
        return True

    def _http_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (compatible; generic-runtime-evidence/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,text/plain;q=0.7,*/*;q=0.5",
            "Accept-Language": "en,ja,zh;q=0.8,*;q=0.5",
        }

    async def fetch(self, *, url: str, timeout_seconds: float = 20.0, max_chars: int = 8000) -> dict[str, Any]:
        url = str(url or "").strip()
        if not self._safe_http_url(url):
            return self._record("fetch", {"status": "error", "url": url, "error": "Only http/https URLs are allowed."})
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, headers=self._http_headers()) as client:
                response = await client.get(url)
                response.raise_for_status()
            raw_html = response.text or ""
            soup = BeautifulSoup(raw_html, "html.parser")
            title = self._clean(soup.title.get_text(" ") if soup.title else "")

            dom_items = self._extract_dom_evidence_items(soup, limit=260)
            dom_text = self._clean(" ".join(item.get("text", "") for item in dom_items))[:max_chars]
            discovered_links = self._extract_discovered_links(soup, base_url=url, limit=240)
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
                "discovered_links": discovered_links[:120],
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


    def _extract_discovered_links(self, soup: BeautifulSoup, *, base_url: str, limit: int = 200) -> list[dict[str, Any]]:
        """Extract same-document child URI candidates from a fetched page.

        This is generic URI exploration material.  It does not classify a page by
        business type.  Downstream retrieval decides whether a URI is useful by
        contract satisfaction, relevance, and consistency.
        """
        links: list[dict[str, Any]] = []
        seen: set[str] = set()
        for tag in soup.find_all("a"):
            href = str(tag.get("href") or "").strip()
            url = self._normalize_search_url(href, base_url=base_url)
            if not self._safe_http_url(url):
                continue
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            normalized = url.split("#", 1)[0].strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            anchor_text = self._clean(tag.get_text(" ", strip=True))
            title = self._clean(str(tag.get("title") or tag.get("aria-label") or ""))
            links.append({
                "url": normalized,
                "anchor_text": anchor_text[:240],
                "title": title[:240],
                "source_url": base_url,
            })
            if len(links) >= limit:
                break
        return links

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

    def _normalize_search_url(self, href: str, base_url: str = "") -> str:
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
        if base_url and href.startswith("/"):
            return urljoin(base_url, href)
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

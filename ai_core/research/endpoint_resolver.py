from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ResolvedEndpoint:
    url: str
    source: str
    confidence: float
    reason: str


class EndpointResolver:
    """Resolve executable network endpoints from documentation evidence.

    Domain-neutral rules only. The resolver does not know provider names or
    business domains. It extracts candidate endpoints from URLs, OpenAPI links,
    curl/fetch examples, and relative paths found in documentation text. It also
    tests generic API subdomain variants for relative endpoint paths so that a
    documentation page is not treated as the executable API base URL.
    """

    API_PATH_HINTS = ("/api/", "/v1/", "/v2/", "/v3/", "/rest/", "/graphql")

    def resolve_from_discovery(self, discovery: dict[str, Any]) -> list[dict[str, Any]]:
        result = discovery.get("result") if isinstance(discovery.get("result"), dict) else {}
        docs = result.get("documentation_understanding") if isinstance(result.get("documentation_understanding"), dict) else {}
        doc_pages = self._document_pages(discovery)
        endpoints: list[ResolvedEndpoint] = []

        request_info = docs.get("request") if isinstance(docs.get("request"), dict) else {}
        for key in ("url", "endpoint", "base_url"):
            raw = str(request_info.get(key) or "").strip()
            if raw:
                endpoints.extend(self.resolve_value(raw, doc_pages=doc_pages, source=f"documentation_understanding.request.{key}"))

        for page in doc_pages:
            base_url = str(page.get("url") or "").strip()
            text = "\n".join(str(page.get(k) or "") for k in ("title", "snippet", "text_excerpt", "sample"))
            endpoints.extend(self.resolve_text(text, base_url=base_url, source="documentation_text"))

        for item in result.get("candidates", []) if isinstance(result.get("candidates"), list) else []:
            if isinstance(item, dict):
                for key in ("url", "endpoint", "official_documentation_url"):
                    raw = str(item.get(key) or "").strip()
                    if raw:
                        endpoints.extend(self.resolve_value(raw, doc_pages=doc_pages, source=f"candidate.{key}"))

        return [asdict(e) for e in self._dedupe(endpoints)]

    def resolve_value(self, value: str, *, doc_pages: list[dict[str, Any]], source: str) -> list[ResolvedEndpoint]:
        value = str(value or "").strip().strip('"\'')
        if not value:
            return []
        if value.startswith(("http://", "https://")):
            return [ResolvedEndpoint(url=value, source=source, confidence=0.8 if self._looks_executable(value) else 0.35, reason="absolute_url")]
        if value.startswith("/"):
            out: list[ResolvedEndpoint] = []
            for page in doc_pages[:6]:
                base_url = str(page.get("url") or "").strip()
                if not base_url:
                    continue
                out.extend(self._relative_endpoint_variants(base_url, value, source=source))
            return out
        return []

    def resolve_text(self, text: str, *, base_url: str, source: str) -> list[ResolvedEndpoint]:
        text = str(text or "")
        endpoints: list[ResolvedEndpoint] = []
        for match in re.finditer(r"https?://[^\s\"'<>`\\)]+", text):
            url = match.group(0).rstrip(".,;)")
            endpoints.append(ResolvedEndpoint(url=url, source=source, confidence=0.85 if self._looks_executable(url) else 0.35, reason="absolute_url_in_text"))
        for match in re.finditer(r"(?<![A-Za-z0-9])(/(?:api|v\d+|rest|graphql)[A-Za-z0-9_./:?=&,%+\-]*)", text):
            path = match.group(1).rstrip(".,;)")
            endpoints.extend(self._relative_endpoint_variants(base_url, path, source=source))
        for match in re.finditer(r"(?:curl|fetch|GET|POST)\s+['\"]?(https?://[^\s\"'<>`\\)]+)", text, flags=re.IGNORECASE):
            url = match.group(1).rstrip(".,;)")
            endpoints.append(ResolvedEndpoint(url=url, source=source, confidence=0.95, reason="request_example_url"))
        return endpoints

    def _relative_endpoint_variants(self, doc_url: str, path: str, *, source: str) -> list[ResolvedEndpoint]:
        parsed = urllib.parse.urlparse(doc_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return []
        host = parsed.netloc
        root = f"{parsed.scheme}://{host}"
        variants = [urllib.parse.urljoin(root, path)]
        bare = host[4:] if host.startswith("www.") else host
        api_host = f"api.{bare}"
        if api_host != host:
            variants.append(urllib.parse.urljoin(f"{parsed.scheme}://{api_host}", path))
        return [ResolvedEndpoint(url=url, source=source, confidence=0.72 if self._looks_executable(url) else 0.4, reason="relative_endpoint_variant") for url in variants]

    def _document_pages(self, discovery: dict[str, Any]) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        result = discovery.get("result") if isinstance(discovery.get("result"), dict) else {}
        for item in discovery.get("documentation_evidence", []) if isinstance(discovery.get("documentation_evidence"), list) else []:
            if isinstance(item, dict):
                doc = item.get("document") if isinstance(item.get("document"), dict) else {}
                search = item.get("source_search_result") if isinstance(item.get("source_search_result"), dict) else {}
                pages.append({**search, **doc})
        for item in result.get("documentation_evidence", []) if isinstance(result.get("documentation_evidence"), list) else []:
            if isinstance(item, dict):
                doc = item.get("document") if isinstance(item.get("document"), dict) else {}
                search = item.get("source_search_result") if isinstance(item.get("source_search_result"), dict) else {}
                pages.append({**search, **doc})
        for item in discovery.get("web_evidence", []) if isinstance(discovery.get("web_evidence"), list) else []:
            if isinstance(item, dict):
                pages.append(item)
        selected = result.get("selected_candidate") if isinstance(result.get("selected_candidate"), dict) else {}
        if selected:
            pages.append({"url": selected.get("official_documentation_url") or selected.get("url"), "title": selected.get("name"), "snippet": selected.get("notes")})
        return self._dedupe_pages(pages)

    def _dedupe_pages(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out, seen = [], set()
        for page in pages:
            url = str(page.get("url") or "").strip()
            key = url or str(page.get("title") or page.get("snippet") or "")[:120]
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(page)
        return out

    def _dedupe(self, endpoints: list[ResolvedEndpoint]) -> list[ResolvedEndpoint]:
        best: dict[str, ResolvedEndpoint] = {}
        for endpoint in endpoints:
            normalized = self._normalize(endpoint.url)
            if not normalized:
                continue
            endpoint.url = normalized
            current = best.get(normalized)
            if current is None or endpoint.confidence > current.confidence:
                best[normalized] = endpoint
        return sorted(best.values(), key=lambda e: -e.confidence)

    def _normalize(self, url: str) -> str:
        try:
            parsed = urllib.parse.urlparse(str(url).strip())
        except Exception:
            return ""
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return urllib.parse.urlunparse(parsed)

    def _looks_executable(self, url: str) -> bool:
        lower = str(url or "").lower()
        return any(hint in lower for hint in self.API_PATH_HINTS) or "openapi" in lower or "swagger" in lower

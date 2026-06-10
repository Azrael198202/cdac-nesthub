from __future__ import annotations

from typing import Any, Awaitable, Callable
from urllib.parse import urlparse


class ContentAcquisitionLayer:
    """Acquire page-level content for selected source candidates.

    This layer is generic orchestration. It accepts a fetch coroutine supplied by
    runtime infrastructure and does not know any domain, provider, or business
    vocabulary.
    """

    async def acquire(
        self,
        *,
        candidates: list[dict[str, Any]],
        fetcher: Callable[..., Awaitable[dict[str, Any]]],
        max_pages: int = 5,
        timeout_seconds: float = 20.0,
        max_chars: int = 12000,
    ) -> list[dict[str, Any]]:
        urls: list[str] = []
        for candidate in candidates:
            url = self._candidate_url(candidate)
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= max_pages:
                break
        docs: list[dict[str, Any]] = []
        for url in urls:
            try:
                payload = await fetcher(url=url, timeout_seconds=timeout_seconds, max_chars=max_chars)
            except TypeError:
                payload = await fetcher(url=url)
            except Exception as exc:
                payload = {"status": "error", "url": url, "error": str(exc)}
            if isinstance(payload, dict):
                docs.append(payload)
        return docs

    def _candidate_url(self, candidate: dict[str, Any]) -> str:
        if not isinstance(candidate, dict):
            return ""
        for key in ("url", "source_url", "official_documentation_url", "href"):
            value = candidate.get(key)
            if isinstance(value, str) and self._safe(value):
                return value.strip()
        for key in ("document", "evidence", "source_search_result"):
            nested = candidate.get(key)
            if isinstance(nested, dict):
                found = self._candidate_url(nested)
                if found:
                    return found
        return ""

    def _safe(self, value: str) -> bool:
        try:
            parsed = urlparse(value)
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False

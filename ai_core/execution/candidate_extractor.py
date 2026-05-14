from __future__ import annotations

from typing import Any


class CandidateExtractor:
    """Extract retry candidates from generic discovery/tool metadata.

    The extractor does not understand domains or providers. It only normalizes
    candidate-like objects and evidence URLs into a stable list of attempts.
    """

    def extract(self, *sources: Any) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for source in sources:
            self._collect(source, output)
        return self._dedupe(output)

    def _collect(self, source: Any, output: list[dict[str, Any]]) -> None:
        if not isinstance(source, dict):
            return
        discovery = source.get("api_discovery") if isinstance(source.get("api_discovery"), dict) else source
        result = discovery.get("result") if isinstance(discovery.get("result"), dict) else {}

        selected = result.get("selected_candidate")
        if isinstance(selected, dict):
            output.append(self._candidate(selected, rank=0, source="selected_candidate"))

        candidates = result.get("candidates")
        if isinstance(candidates, list):
            for idx, candidate in enumerate(candidates, start=1):
                if isinstance(candidate, dict):
                    output.append(self._candidate(candidate, rank=idx, source="candidate_list"))

        for idx, item in enumerate(discovery.get("documentation_evidence") or [], start=100):
            if not isinstance(item, dict):
                continue
            doc = item.get("document") if isinstance(item.get("document"), dict) else {}
            search = item.get("source_search_result") if isinstance(item.get("source_search_result"), dict) else {}
            url = str(doc.get("url") or search.get("url") or "").strip()
            if url:
                output.append({
                    "name": str(doc.get("title") or search.get("title") or url),
                    "url": url,
                    "official_documentation_url": url,
                    "rank": idx,
                    "source": "documentation_evidence",
                    "evidence": item,
                })

        for idx, item in enumerate(discovery.get("web_evidence") or [], start=200):
            if isinstance(item, dict) and item.get("url"):
                output.append({
                    "name": str(item.get("title") or item.get("url")),
                    "url": str(item.get("url")),
                    "official_documentation_url": str(item.get("url")),
                    "rank": idx,
                    "source": "web_evidence",
                    "evidence": item,
                })

    def _candidate(self, value: dict[str, Any], *, rank: int, source: str) -> dict[str, Any]:
        url = str(value.get("official_documentation_url") or value.get("url") or value.get("endpoint") or "").strip()
        return {
            **value,
            "url": url,
            "official_documentation_url": url or str(value.get("official_documentation_url") or ""),
            "rank": rank,
            "source": source,
        }

    def _dedupe(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        output: list[dict[str, Any]] = []
        for item in sorted(items, key=lambda x: int(x.get("rank") or 9999)):
            key = str(item.get("official_documentation_url") or item.get("url") or item.get("name") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(item)
        return output

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class NormalizedEvidenceRecord:
    title: str
    url: str
    host: str
    text: str
    source_type: str
    relevance_score: float
    matched_terms: tuple[str, ...]
    kind: str = ""
    time_expression: str = ""
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["matched_terms"] = list(self.matched_terms)
        return data


class EvidenceNormalizationLayer:
    """Convert heterogeneous result material into source-grounded records.

    The layer is domain-neutral.  It knows nothing about a product, vendor,
    database, service, or business task.  It only finds title/url/text carriers,
    removes empty records, deduplicates by source, and preserves relevance
    metadata for later claim resolution.
    """

    TEXT_KEYS = (
        "text", "text_excerpt", "visible_text_excerpt", "dom_evidence_text",
        "snippet", "summary", "description", "content", "value", "context",
    )
    TITLE_KEYS = ("title", "name", "label")
    URL_KEYS = ("url", "source_url", "href", "evidence_url", "official_documentation_url")

    def normalize(self, *, user_input: str = "", materials: list[Any] | None = None, source_cards: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        raw_items: list[Any] = []
        if source_cards:
            raw_items.extend(source_cards)
        if materials:
            raw_items.extend(materials)

        records: list[NormalizedEvidenceRecord] = []
        for item in raw_items:
            records.extend(self._records_from_any(item))

        deduped: dict[str, NormalizedEvidenceRecord] = {}
        for record in records:
            if not record.text and not record.title:
                continue
            key = record.url or f"{record.title}|{record.text[:120]}"
            current = deduped.get(key)
            if current is None or self._record_score(record) > self._record_score(current):
                deduped[key] = record

        selected = sorted(deduped.values(), key=self._record_score, reverse=True)[:12]
        return {
            "user_input": str(user_input or ""),
            "records": [record.to_dict() for record in selected],
            "source_urls": [r.url for r in selected if r.url.startswith(("http://", "https://"))],
            "record_count": len(selected),
        }

    def _records_from_any(self, value: Any, inherited_url: str = "", inherited_title: str = "", depth: int = 0) -> list[NormalizedEvidenceRecord]:
        if depth > 6:
            return []
        records: list[NormalizedEvidenceRecord] = []
        if isinstance(value, dict):
            url = inherited_url
            for key in self.URL_KEYS:
                raw = value.get(key)
                if isinstance(raw, str) and raw.strip().startswith(("http://", "https://")):
                    url = raw.strip()
                    break
            title = inherited_title
            for key in self.TITLE_KEYS:
                raw = value.get(key)
                if isinstance(raw, str) and raw.strip():
                    title = " ".join(raw.split())[:240]
                    break
            texts: list[str] = []
            for key in self.TEXT_KEYS:
                raw = value.get(key)
                if isinstance(raw, str) and raw.strip():
                    texts.append(" ".join(raw.split()))
            if texts or title or url:
                text = " ".join(texts)[:2400]
                records.append(NormalizedEvidenceRecord(
                    title=title or self._title_from_url(url),
                    url=url[:500],
                    host=urlparse(url).netloc.casefold(),
                    text=text,
                    source_type=str(value.get("source") or value.get("provider") or value.get("source_type") or "source"),
                    relevance_score=float(value.get("relevance_score") or 0.0) if self._is_number(value.get("relevance_score")) else 0.0,
                    matched_terms=tuple(str(x) for x in value.get("matched_terms", []) if str(x).strip()) if isinstance(value.get("matched_terms"), list) else tuple(),
                    kind=str(value.get("kind") or ""),
                    time_expression=str(value.get("time_expression") or ""),
                    source_url=str(value.get("source_url") or ""),
                ))
            for child in value.values():
                if isinstance(child, (dict, list)):
                    records.extend(self._records_from_any(child, url, title, depth + 1))
        elif isinstance(value, list):
            for item in value[:80]:
                records.extend(self._records_from_any(item, inherited_url, inherited_title, depth + 1))
        elif isinstance(value, str) and value.strip():
            text = " ".join(value.split())[:2400]
            records.append(NormalizedEvidenceRecord(
                title=inherited_title,
                url=inherited_url,
                host=urlparse(inherited_url).netloc.casefold(),
                text=text,
                source_type="text",
                relevance_score=0.0,
                matched_terms=tuple(),
                kind="text",
                time_expression="",
                source_url=inherited_url,
            ))
        return records

    def _record_score(self, record: NormalizedEvidenceRecord) -> tuple[float, int, int, int]:
        numeric = 1 if re.search(r"\d", f"{record.title} {record.text}") else 0
        host_strength = 1 if record.host else 0
        return (record.relevance_score, host_strength, numeric, len(record.text))

    def _title_from_url(self, url: str) -> str:
        host = urlparse(url or "").netloc
        return host or "source"

    def _is_number(self, value: Any) -> bool:
        try:
            float(value)
            return True
        except Exception:
            return False

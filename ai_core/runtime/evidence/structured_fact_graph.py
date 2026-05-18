from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


@dataclass
class StructuredFact:
    entity: str | None = None
    time: str | None = None
    attribute: str | None = None
    value: str | None = None
    unit: str | None = None
    source_url: str | None = None
    confidence: float = 0.0
    evidence_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "time": self.time,
            "attribute": self.attribute,
            "value": self.value,
            "unit": self.unit,
            "source_url": self.source_url,
            "confidence": round(float(self.confidence), 3),
            "evidence_text": self.evidence_text[:500],
        }


class StructuredFactGraph:
    """Builds a generic fact graph from evidence text.

    The implementation is intentionally domain-neutral. It extracts time-like
    expressions, numeric values with optional units, and nearby labels without
    assuming any business domain.
    """

    DATE_PATTERNS = [
        r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b",
        r"\b\d{1,2}\s+[A-Za-z]{3,12}\s+\d{4}\b",
        r"\b[A-Za-z]{3,12}\s+\d{1,2}\s+\d{4}\b",
        r"\b\d{1,2}\s+[A-Za-z]{3,12}\b",
        r"\b[A-Za-z]{3,12}\s+\d{1,2}\b",
    ]
    VALUE_PATTERN = re.compile(r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>[%°A-Za-z/]+)?")

    def build(self, *, evidence_items: list[dict[str, Any]], known_parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        facts: list[StructuredFact] = []
        for item in evidence_items:
            text = self._join_text(item)
            if not text:
                continue
            source_url = item.get("url") or item.get("source_url")
            facts.extend(self._extract_facts(text=text, source_url=source_url, known=known_parameters or {}))
        return {
            "type": "structured_fact_graph",
            "fact_count": len(facts),
            "facts": [f.to_dict() for f in facts[:100]],
            "coverage": self._coverage([f.to_dict() for f in facts], known_parameters or {}),
        }

    def _join_text(self, item: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("title", "snippet", "text_excerpt", "html_excerpt", "dom_evidence_text", "visible_text"):
            value = item.get(key)
            if isinstance(value, str):
                parts.append(value)
        document = item.get("document") if isinstance(item.get("document"), dict) else {}
        for key in ("title", "text_excerpt", "html_excerpt", "dom_evidence_text", "visible_text"):
            value = document.get(key)
            if isinstance(value, str):
                parts.append(value)
        return "\n".join(parts)

    def _extract_facts(self, *, text: str, source_url: str | None, known: dict[str, Any]) -> list[StructuredFact]:
        windows: list[tuple[str | None, str]] = []
        for pattern in self.DATE_PATTERNS:
            for match in re.finditer(pattern, text, flags=re.I):
                start = max(0, match.start() - 160)
                end = min(len(text), match.end() + 220)
                windows.append((match.group(0), text[start:end]))
        if not windows:
            windows.append((None, text[:1200]))
        facts: list[StructuredFact] = []
        entity = self._best_entity_hint(known)
        for time_value, window in windows[:30]:
            for value_match in self.VALUE_PATTERN.finditer(window):
                raw_value = value_match.group("value")
                if raw_value is None:
                    continue
                unit = value_match.group("unit") or None
                attribute = self._nearby_label(window, value_match.start())
                facts.append(StructuredFact(
                    entity=entity,
                    time=time_value,
                    attribute=attribute,
                    value=raw_value,
                    unit=unit,
                    source_url=source_url,
                    confidence=0.55 + (0.2 if time_value else 0.0) + (0.1 if unit else 0.0),
                    evidence_text=window,
                ))
        return facts

    def _best_entity_hint(self, known: dict[str, Any]) -> str | None:
        for key, value in known.items():
            if isinstance(value, str) and value.strip() and not self._looks_temporal(value):
                return value.strip()
        return None

    def _looks_temporal(self, value: str) -> bool:
        return bool(re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", value, flags=re.I))

    def _nearby_label(self, text: str, index: int) -> str | None:
        left = text[max(0, index - 80):index]
        tokens = re.findall(r"[\w\-/%°]+", left, flags=re.UNICODE)
        if not tokens:
            return None
        return " ".join(tokens[-4:])[:80]

    def _coverage(self, facts: list[dict[str, Any]], known: dict[str, Any]) -> dict[str, Any]:
        hay = "\n".join(str(f) for f in facts).lower()
        matched = []
        missing = []
        for key, value in known.items():
            needle = str(value).strip().lower()
            if not needle:
                continue
            if needle in hay or any(part and part in hay for part in re.split(r"[,\s/|;]+", needle)):
                matched.append(key)
            else:
                missing.append(key)
        return {"matched": matched, "missing": missing, "passed": not missing}

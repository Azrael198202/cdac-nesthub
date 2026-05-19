from __future__ import annotations

import re
from typing import Any


class FactTypeInferencer:
    """Infers generic semantic types for extracted facts.

    The implementation is domain-neutral. It does not know what a value is used
    for in a business scenario; it only classifies numeric and textual evidence
    by generic shape, unit, and local context.
    """

    COORDINATE_TOKEN = re.compile(
        r"(?<![A-Za-z0-9])[-+]?\d{1,3}(?:\.\d+)?\s*°\s*[NSEW](?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    DIRECTION_AFTER_VALUE = re.compile(r"^\s*[NSEW]\b", re.IGNORECASE)
    ISO_LIKE = re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?\b")
    CLOCK_LIKE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
    NUMBER_LIKE = re.compile(r"^[-+]?\d+(?:\.\d+)?$")

    def infer(self, fact: dict[str, Any]) -> dict[str, Any]:
        value = str(fact.get("value") or "").strip()
        unit = str(fact.get("unit") or "").replace(" ", "").strip()
        context = str(fact.get("context") or fact.get("evidence_text") or "")
        label = str(fact.get("label") or fact.get("attribute") or "")
        combined = " ".join(x for x in (label, value, unit, context) if x)

        semantic_type = "text"
        if self._looks_like_coordinate(value=value, unit=unit, context=context):
            semantic_type = "coordinate"
        elif unit == "%":
            semantic_type = "bounded_ratio"
        elif self._looks_like_temporal(value) or self._looks_like_temporal(combined):
            semantic_type = "temporal_marker"
        elif unit:
            semantic_type = "measurement"
        elif self.NUMBER_LIKE.match(value):
            semantic_type = "number"

        enriched = dict(fact)
        enriched["semantic_type"] = semantic_type
        enriched["semantic_type_confidence"] = self._confidence(semantic_type, unit, context)
        return enriched

    def _looks_like_coordinate(self, *, value: str, unit: str, context: str) -> bool:
        # Only classify the observed value itself as a coordinate.  A context
        # window may contain many unrelated numbers; seeing a coordinate
        # elsewhere in the same window must not poison all neighboring facts.
        sample = context or ""
        value_text = value.strip()
        if value_text and self.COORDINATE_TOKEN.fullmatch(value_text):
            return True
        if unit.startswith("°") and not unit.casefold().startswith(("°c", "°f")):
            after = self._text_after_value(sample, value_text)
            if self.DIRECTION_AFTER_VALUE.match(after):
                return True
        return False

    def _text_after_value(self, text: str, value: str) -> str:
        if not value:
            return ""
        idx = text.find(value)
        if idx < 0:
            return ""
        return text[idx + len(value): idx + len(value) + 12]

    def _looks_like_temporal(self, text: str) -> bool:
        return bool(self.ISO_LIKE.search(text) or self.CLOCK_LIKE.search(text))

    def _confidence(self, semantic_type: str, unit: str, context: str) -> float:
        score = 0.55
        if semantic_type in {"coordinate", "bounded_ratio", "temporal_marker"}:
            score += 0.25
        if unit:
            score += 0.1
        if context:
            score += 0.05
        return min(score, 0.95)

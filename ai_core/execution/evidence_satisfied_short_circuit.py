from __future__ import annotations

from typing import Any


class EvidenceSatisfiedShortCircuit:
    """Decide whether collected evidence is already sufficient.

    This component is intentionally domain-neutral.  It only looks at generic
    sufficiency metadata, coverage, confidence, and available evidence text.
    It never names a business capability, provider, website, or answer domain.
    """

    DEFAULT_MIN_CONFIDENCE = 0.72

    def should_bypass_generated_execution(self, *sources: Any, min_confidence: float | None = None) -> bool:
        min_confidence = self.DEFAULT_MIN_CONFIDENCE if min_confidence is None else float(min_confidence)
        for source in sources:
            if self._source_is_sufficient(source, min_confidence=min_confidence):
                return True
        return False

    def _source_is_sufficient(self, source: Any, *, min_confidence: float) -> bool:
        if not isinstance(source, dict):
            return False

        if self._sufficiency_result_passed(source, min_confidence=min_confidence):
            return True

        for key in (
            "answer_sufficiency",
            "sufficiency",
            "evidence_sufficiency",
            "quality",
            "verification",
            "api_discovery",
            "external_solution_discovery",
            "result",
            "data",
        ):
            nested = source.get(key)
            if isinstance(nested, dict) and self._source_is_sufficient(nested, min_confidence=min_confidence):
                return True

        for key in ("selected_evidence", "evidence", "documents", "web_results", "documentation_evidence"):
            items = source.get(key)
            if isinstance(items, list) and self._evidence_list_is_sufficient(items, min_confidence=min_confidence):
                return True
        return False

    def _sufficiency_result_passed(self, value: dict[str, Any], *, min_confidence: float) -> bool:
        if value.get("passed") is True:
            score = self._float(value.get("score"), default=1.0)
            if score >= min_confidence:
                return True
        coverage = value.get("coverage") if isinstance(value.get("coverage"), dict) else value.get("aggregate_coverage")
        if isinstance(coverage, dict) and coverage.get("passed") is True:
            score = max(
                self._float(value.get("confidence"), default=0.0),
                self._float(value.get("score"), default=0.0),
                self._float(coverage.get("coverage_ratio"), default=0.0),
            )
            if score >= min_confidence:
                return True
        return False

    def _evidence_list_is_sufficient(self, items: list[Any], *, min_confidence: float) -> bool:
        for item in items:
            if not isinstance(item, dict):
                continue
            coverage = item.get("coverage") if isinstance(item.get("coverage"), dict) else {}
            confidence = max(
                self._float(item.get("confidence"), default=0.0),
                self._float(item.get("score"), default=0.0),
                self._float(coverage.get("coverage_ratio"), default=0.0),
            )
            if coverage.get("passed") is True and confidence >= min_confidence and self._has_answer_material(item):
                return True
        return False

    def _has_answer_material(self, item: dict[str, Any]) -> bool:
        texts = []
        containers = [item]
        for key in ("evidence", "document", "source_search_result"):
            nested = item.get(key)
            if isinstance(nested, dict):
                containers.append(nested)
                doc = nested.get("document")
                if isinstance(doc, dict):
                    containers.append(doc)
        for container in containers:
            if not isinstance(container, dict):
                continue
            for key in ("text_excerpt", "visible_text_excerpt", "dom_evidence_text", "html_excerpt", "snippet", "title", "description"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    texts.append(value.strip())
        return len("\n".join(texts).strip()) >= 80

    def _float(self, value: Any, *, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

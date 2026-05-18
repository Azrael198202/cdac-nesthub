from __future__ import annotations

from collections import defaultdict
from typing import Any


class EvidenceVerifier:
    """Validates source diversity, fact coverage, and confidence using neutral contracts."""

    def verify(self, evidence_items: list[dict[str, Any]], required_dimensions: list[str] | None = None) -> dict[str, Any]:
        dimensions = [str(x) for x in (required_dimensions or []) if str(x).strip()]
        source_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        dimension_hits = {dimension: 0 for dimension in dimensions}
        valid_items: list[dict[str, Any]] = []

        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or item.get("source_url") or item.get("source") or "unknown")
            facts = item.get("facts") or item.get("structured_evidence") or []
            text = str(item.get("text") or item.get("excerpt") or item.get("content") or item)
            if facts or text.strip():
                valid_items.append(item)
                source_map[source_id].append(item)
                for dimension in dimensions:
                    if dimension and dimension.lower() in text.lower():
                        dimension_hits[dimension] += 1

        source_count = len([key for key in source_map if key != "unknown"])
        if source_count == 0 and valid_items:
            source_count = 1
        coverage_ratio = 1.0 if not dimensions else sum(1 for count in dimension_hits.values() if count > 0) / len(dimensions)
        source_score = min(source_count / 2, 1.0)
        confidence = round((coverage_ratio * 0.6) + (source_score * 0.4), 3)
        return {
            "passed": bool(valid_items) and confidence >= 0.6,
            "confidence": confidence,
            "source_count": source_count,
            "coverage_ratio": round(coverage_ratio, 3),
            "dimension_hits": dimension_hits,
            "issues": self._issues(valid_items, source_count, coverage_ratio),
        }

    def _issues(self, valid_items: list[dict[str, Any]], source_count: int, coverage_ratio: float) -> list[str]:
        issues: list[str] = []
        if not valid_items:
            issues.append("no_evidence_material")
        if source_count < 2:
            issues.append("insufficient_source_diversity")
        if coverage_ratio < 1.0:
            issues.append("incomplete_dimension_coverage")
        return issues

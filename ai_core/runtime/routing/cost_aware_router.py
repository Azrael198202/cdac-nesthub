from __future__ import annotations

from typing import Any


class CostAwareRouter:
    """Provider-neutral routing by budget, latency, and quality hints."""

    def rank(self, candidates: list[dict[str, Any]], requirement: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        requirement = requirement or {}
        ranked = []
        for candidate in candidates:
            score = self._score(candidate, requirement)
            item = dict(candidate)
            item["routing_score"] = round(score, 4)
            ranked.append(item)
        ranked.sort(key=lambda x: x.get("routing_score", 0), reverse=True)
        return ranked

    def _score(self, candidate: dict[str, Any], requirement: dict[str, Any]) -> float:
        quality = float(candidate.get("quality_score") or candidate.get("quality") or 0.5)
        latency = float(candidate.get("latency_ms") or 1000)
        cost = float(candidate.get("unit_cost") or 0)
        local_bonus = 0.15 if candidate.get("is_local") else 0
        max_latency = float(requirement.get("max_latency_ms") or 30000)
        max_cost = float(requirement.get("max_unit_cost") or 1)
        latency_score = max(0.0, 1.0 - latency / max_latency)
        cost_score = max(0.0, 1.0 - cost / max_cost) if max_cost > 0 else 0.0
        return quality * 0.5 + latency_score * 0.2 + cost_score * 0.2 + local_bonus

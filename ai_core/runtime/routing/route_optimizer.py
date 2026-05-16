from __future__ import annotations

from typing import Any


class RouteOptimizer:
    """Ranks execution routes by quality, reliability, cost, and latency."""

    def optimize(self, candidates: list[dict[str, Any]], constraints: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        constraints = constraints or {}
        max_cost = constraints.get("max_unit_cost")
        filtered: list[dict[str, Any]] = []
        for candidate in candidates:
            if max_cost is not None and float(candidate.get("unit_cost", 0) or 0) > float(max_cost):
                continue
            scored = dict(candidate)
            scored["score"] = self._score(candidate)
            filtered.append(scored)
        return sorted(filtered, key=lambda item: item["score"], reverse=True)

    def _score(self, candidate: dict[str, Any]) -> float:
        quality = float(candidate.get("quality", 0.5) or 0.5)
        reliability = float(candidate.get("reliability", 0.5) or 0.5)
        latency_ms = max(float(candidate.get("latency_ms", 1000) or 1000), 1.0)
        unit_cost = max(float(candidate.get("unit_cost", 0) or 0), 0.0)
        latency_score = min(1000.0 / latency_ms, 1.0)
        cost_score = 1.0 / (1.0 + unit_cost)
        return round((quality * 0.45) + (reliability * 0.35) + (latency_score * 0.1) + (cost_score * 0.1), 4)

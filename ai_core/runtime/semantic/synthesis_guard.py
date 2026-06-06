from __future__ import annotations

from typing import Any


class SynthesisGuard:
    """Filters synthesis inputs to verified, user-facing facts."""

    def filter(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            if fact.get("verified") is not True:
                continue
            cleaned = {k: v for k, v in fact.items() if k not in {"semantic_validation"}}
            result.append(cleaned)
        return result

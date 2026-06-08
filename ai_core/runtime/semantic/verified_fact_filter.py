from __future__ import annotations

from typing import Any


class VerifiedFactFilter:
    def filter(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [fact for fact in facts if isinstance(fact, dict) and fact.get("verified") is True]

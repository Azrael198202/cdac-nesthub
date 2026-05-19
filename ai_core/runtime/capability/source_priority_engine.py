from __future__ import annotations

from typing import Any


class SourcePriorityEngine:
    """Ranks execution modes using runtime-provided policy.

    The engine is intentionally generic.  It does not know domain fields; it
    only compares execution mode identifiers declared by config or runtime
    contracts.
    """

    DEFAULT_ORDER = ["runtime_native", "structured_provider", "web_retrieval"]

    def order(self, policy: dict[str, Any] | None = None) -> list[str]:
        policy = policy or {}
        configured = policy.get("preferred_execution_modes")
        if isinstance(configured, list) and configured:
            return [str(x) for x in configured if str(x).strip()]
        return list(self.DEFAULT_ORDER)

    def rank(self, mode: str, policy: dict[str, Any] | None = None) -> int:
        ordered = self.order(policy)
        try:
            return len(ordered) - ordered.index(mode)
        except ValueError:
            return 0

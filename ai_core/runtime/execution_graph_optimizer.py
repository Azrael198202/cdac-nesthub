from __future__ import annotations

from typing import Any


class ExecutionGraphOptimizer:
    """Optimizes a generic execution strategy based on available evidence."""

    DEFAULT_STRATEGY = ["local_knowledge", "web_evidence", "tool_generation"]

    def optimize(self, strategy: list[str] | None, state: dict[str, Any] | None = None) -> list[str]:
        state = state or {}
        steps = list(strategy or self.DEFAULT_STRATEGY)
        if state.get("verified_material_available"):
            return [step for step in steps if step != "tool_generation"]
        if state.get("skip_local_lookup"):
            steps = [step for step in steps if step != "local_knowledge"]
        return steps

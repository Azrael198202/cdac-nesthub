from __future__ import annotations

from typing import Any, Callable


class RegressionReplayRunner:
    """Runs deterministic replay scenarios."""

    def run(self, scenarios: list[dict[str, Any]], executor: Callable[[dict[str, Any]], dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for scenario in scenarios:
            output = executor(scenario)
            results.append({"name": scenario.get("name"), "passed": bool(output.get("passed")), "output": output})
        return results

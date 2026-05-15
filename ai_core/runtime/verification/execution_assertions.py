from __future__ import annotations

from typing import Iterable


class ExecutionAssertions:
    """Asserts required runtime state transitions occurred."""

    def require_events(self, actual_events: Iterable[str], required_events: Iterable[str]) -> dict:
        actual = list(actual_events)
        missing = [event for event in required_events if event not in actual]
        return {"passed": not missing, "missing": missing, "actual": actual}

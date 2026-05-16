from __future__ import annotations

from typing import Any, Callable

from ai_core.runtime.verification.failure_taxonomy import FailureClassifier


class SelfHealingRuntime:
    """Attempts bounded autonomous repair using generic failure classification."""

    def repair(self, failure: dict[str, Any], strategies: list[Callable[[dict[str, Any]], dict[str, Any]]]) -> dict[str, Any]:
        kind = FailureClassifier().classify(failure)
        attempts: list[dict[str, Any]] = []
        for strategy in strategies:
            outcome = strategy({"failure": failure, "failure_kind": getattr(kind, "value", str(kind))})
            attempts.append(outcome)
            if outcome.get("status") in {"success", "repaired"}:
                return {"status": "repaired", "failure_kind": getattr(kind, "value", str(kind)), "attempts": attempts}
        return {"status": "unrepaired", "failure_kind": getattr(kind, "value", str(kind)), "attempts": attempts}

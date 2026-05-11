from __future__ import annotations

from typing import Any


class StepValidator:
    def validate(self, step: str, output: dict[str, Any]) -> dict[str, Any]:
        if not output:
            return {"passed": False, "score": 0.0, "issues": ["empty_output"]}
        if step == "intent_recognition" and "intent_type" not in output:
            return {"passed": False, "score": 0.2, "issues": ["missing_intent_type"]}
        if step == "workflow_planning" and "nodes" not in output:
            return {"passed": False, "score": 0.2, "issues": ["missing_nodes"]}
        return {"passed": True, "score": 0.8, "issues": []}

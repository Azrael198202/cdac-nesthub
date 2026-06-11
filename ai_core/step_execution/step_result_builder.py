from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StepResultBuilder:
    def build(self, *, step_request: dict[str, Any], raw_result: dict[str, Any] | None = None) -> dict[str, Any]:
        result = raw_result if isinstance(raw_result, dict) else {}
        status = str(result.get("status") or "completed")
        return {
            "task_session_id": step_request.get("task_session_id"),
            "step_execution_id": step_request.get("step_execution_id"),
            "step_id": step_request.get("step_id"),
            "status": status,
            "verified_result": result.get("verified_result") if "verified_result" in result else result,
            "presentation": result.get("presentation") if isinstance(result.get("presentation"), dict) else {},
            "errors": result.get("errors") if isinstance(result.get("errors"), list) else [],
        }

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PresentationBridge:
    """Converts verified results into presentation output and exportable assets."""

    failure_statuses: frozenset[str] = frozenset({"failed", "blocked", "error", "requires_input", "paused"})

    def build(self, verified_result: dict[str, Any], presentation_output: dict[str, Any] | None = None) -> dict[str, Any]:
        verified = verified_result if isinstance(verified_result, dict) else {}
        presentation = presentation_output if isinstance(presentation_output, dict) else {}
        status = str(verified.get("status") or presentation.get("status") or "completed")
        final_answer = presentation.get("final_answer", verified.get("final_answer", ""))
        exportable_outputs: dict[str, Any] = {}
        if self._looks_like_failure_message(final_answer):
            status = "failed" if status == "completed" else status
        if status not in self.failure_statuses:
            exportable_outputs = {
                key: value
                for key, value in {
                    "presentation.final_answer": final_answer,
                    "presentation.structured": presentation.get("structured"),
                    "presentation.artifacts": presentation.get("artifacts"),
                }.items()
                if value not in (None, "", [], {})
            }
        return {
            "status": status,
            "verified_result": verified,
            "presentation_output": {**presentation, "final_answer": final_answer},
            "exportable_outputs": exportable_outputs,
            "failure_message_export_blocked": status in self.failure_statuses,
        }

    def _looks_like_failure_message(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        text = value.strip()
        if not text:
            return False
        failure_markers = (
            "Traceback",
            "AttributeError",
            "Exception:",
            " object has no attribute ",
            "template_resolution_problem",
            "{{",
            "}}",
        )
        return any(marker in text for marker in failure_markers)

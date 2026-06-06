from __future__ import annotations

from typing import Any


class RerunStrategy:
    """Selects a generic rerun boundary for feedback-driven adaptation."""

    def choose(self, *, feedback: dict[str, Any], run_payload: dict[str, Any]) -> dict[str, Any]:
        target_node = str(feedback.get("target_node") or "output")
        requested = str(feedback.get("requested_action") or "")
        if requested == "rerun_with_escalation":
            return {
                "strategy": "node_level_resynthesis",
                "target_node": target_node,
                "reuse_completed_participant_results": True,
                "model_escalation": True,
            }
        return {
            "strategy": "record_only",
            "target_node": target_node,
            "reuse_completed_participant_results": True,
            "model_escalation": False,
        }

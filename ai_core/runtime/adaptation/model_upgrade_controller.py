from __future__ import annotations

from typing import Any

from ai_core.runtime.modeling import FeedbackEscalator


class ModelUpgradeController:
    """Records generic feedback signals that cause model-route escalation."""

    def __init__(self) -> None:
        self.feedback = FeedbackEscalator()

    def record_upgrade_request(self, *, target_node: str = "output", reason: str = "user_feedback", message: str = "") -> dict[str, Any]:
        adapter = {
            "adapter_id": "studio_feedback_adaptation",
            "runtime_role": "final_user_response",
            "route_name": "stable_synthesis",
            "escalate_route_name": "stable_synthesis_strong",
        }
        event = {
            "kind": "dissatisfied",
            "reason": reason,
            "message": message,
            "requested_action": "model_escalation",
            "quality_score": 0.0,
        }
        self.feedback.record_event(node_id=target_node, adapter=adapter, event=event)
        return {"status": "recorded", "target_node": target_node, "event": event}

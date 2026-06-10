from __future__ import annotations

from typing import Any


class FinalAnswerGuard:
    """Prevents unsupported success claims for runtime actions."""

    def evaluate(self, *, requested_external_action: bool, result_material: dict[str, Any] | None, draft_answer: str = "") -> dict[str, Any]:
        material = result_material if isinstance(result_material, dict) else {}
        verified = bool(material.get("verified") or material.get("evidence_present") or material.get("verified_result_material"))
        external_executed = bool(material.get("external_action_executed"))
        success_claim = self._looks_like_success(draft_answer)
        if requested_external_action and success_claim and not (verified and external_executed):
            return {
                "passed": False,
                "status": "blocked_unverified_external_action_success_claim",
                "reason": "Success claim requires verified execution material and external_action_executed=true.",
            }
        if success_claim and not verified:
            return {
                "passed": False,
                "status": "blocked_unverified_success_claim",
                "reason": "Success claim requires verified result material.",
            }
        return {"passed": True, "status": "allowed"}

    def _looks_like_success(self, answer: str) -> bool:
        text = str(answer or "").casefold()
        markers = [
            "successfully",
            "completed",
            "done",
            "executed successfully",
        ]
        return any(m in text for m in markers)

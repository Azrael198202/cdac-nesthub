from __future__ import annotations

from typing import Any


class ApprovalService:
    def requires_review(self, node: dict[str, Any], state: dict[str, Any]) -> bool:
        return bool(node.get("human_review"))

    def create_checkpoint(self, node: dict[str, Any], result: Any) -> dict[str, Any]:
        return {
            "node_id": node.get("id"),
            "review_required": True,
            "result_preview": result,
            "message": "Please review the generated result before the next step.",
        }

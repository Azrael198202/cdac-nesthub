from __future__ import annotations

from typing import Any


class ApprovalService:
    def request_approval(self, step: str, payload: dict[str, Any], interactive: bool = False) -> dict[str, Any]:
        if not interactive:
            return {"approved": False, "mode": "non_interactive", "note": "Approval required; demo does not book real flights."}
        answer = input(f"Approve step {step}? y/N: ").strip().lower()
        return {"approved": answer == "y", "mode": "interactive"}

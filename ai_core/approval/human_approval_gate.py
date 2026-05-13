from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_DIR


@dataclass
class ApprovalDecision:
    status: str
    request_id: str
    approved: bool
    requires_human_action: bool
    request_path: str
    reason: str


class HumanApprovalGate:
    """File-based approval gate for risky runtime operations.

    The runtime writes approval requests under runtime/approvals. A user or
    operator can approve by editing the generated JSON and setting approved=true.
    Until then, dependency installation, repo execution, and other risky actions
    remain blocked.
    """

    def __init__(self) -> None:
        self.root = RUNTIME_DIR / "approvals"
        self.root.mkdir(parents=True, exist_ok=True)

    def request(self, *, operation: str, subject: dict[str, Any], risks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        request_id = self._request_id(operation)
        path = self.root / f"{request_id}.json"
        payload = {
            "request_id": request_id,
            "operation": operation,
            "subject": subject,
            "risks": risks or [],
            "approved": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "instructions": "Review this file. Set approved to true only after manual review.",
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return asdict(ApprovalDecision(
            status="approval_required",
            request_id=request_id,
            approved=False,
            requires_human_action=True,
            request_path=str(path),
            reason="Human approval is required before this operation can continue.",
        ))

    def check(self, request_id: str) -> dict[str, Any]:
        path = self.root / f"{request_id}.json"
        if not path.exists():
            return asdict(ApprovalDecision("missing", request_id, False, True, str(path), "Approval request not found."))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return asdict(ApprovalDecision("invalid", request_id, False, True, str(path), str(exc)))
        approved = bool(payload.get("approved"))
        return asdict(ApprovalDecision(
            status="approved" if approved else "pending",
            request_id=request_id,
            approved=approved,
            requires_human_action=not approved,
            request_path=str(path),
            reason="Approved." if approved else "Approval is still pending.",
        ))

    def _request_id(self, operation: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        safe = "".join(c if c.isalnum() else "_" for c in operation).strip("_").lower() or "operation"
        return f"{stamp}_{safe}"

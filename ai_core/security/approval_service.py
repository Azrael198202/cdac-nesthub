from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import uuid


@dataclass
class ApprovalRequest:
    approval_id: str
    action: str
    message: str
    payload: dict[str, Any]


class ApprovalService:
    def __init__(self):
        self.pending: dict[str, ApprovalRequest] = {}
        self.decisions: dict[str, dict[str, Any]] = {}

    def create(self, action: str, message: str, payload: dict[str, Any]) -> ApprovalRequest:
        req = ApprovalRequest(str(uuid.uuid4())[:12], action, message, payload)
        self.pending[req.approval_id] = req
        return req

    def decide(self, approval_id: str, approved: bool, comment: str = "") -> dict[str, Any]:
        req = self.pending.pop(approval_id, None)
        decision = {"approval_id": approval_id, "approved": approved, "comment": comment}
        if req:
            decision["action"] = req.action
            decision["payload"] = req.payload
        self.decisions[approval_id] = decision
        return decision

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self.pending.get(approval_id)

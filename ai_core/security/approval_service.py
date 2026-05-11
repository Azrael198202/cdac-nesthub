from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import json
import uuid


@dataclass
class ApprovalRequest:
    approval_id: str
    action: str
    message: str
    payload: dict[str, Any]


class ApprovalService:
    """In-memory approval registry with generic pre-approval support.

    This service does not know business details. It stores whether a generic action
    with a generic payload was approved, so a resumed workflow can continue without
    asking the same approval again.
    """

    def __init__(self):
        self.pending: dict[str, ApprovalRequest] = {}
        self.decisions: dict[str, dict[str, Any]] = {}
        self.approved_signatures: set[str] = set()

    def _signature(self, action: str, payload: dict[str, Any]) -> str:
        return action + ":" + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)

    def is_approved(self, action: str, payload: dict[str, Any]) -> bool:
        return self._signature(action, payload) in self.approved_signatures

    def create(self, action: str, message: str, payload: dict[str, Any]) -> ApprovalRequest:
        req = ApprovalRequest(str(uuid.uuid4())[:12], action, message, payload)
        self.pending[req.approval_id] = req
        return req

    def decide(self, approval_id: str, approved: bool, comment: str = "") -> dict[str, Any]:
        req = self.pending.pop(approval_id, None)
        decision: dict[str, Any] = {"approval_id": approval_id, "approved": approved, "comment": comment}
        if req:
            decision["action"] = req.action
            decision["payload"] = req.payload
            if approved:
                self.approved_signatures.add(self._signature(req.action, req.payload))
        self.decisions[approval_id] = decision
        return decision

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self.pending.get(approval_id)

    def decision(self, approval_id: str) -> dict[str, Any] | None:
        return self.decisions.get(approval_id)

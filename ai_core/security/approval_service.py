class ApprovalService:
    def requires_approval(self, action: dict) -> bool:
        return bool(action.get("approval_required", True))

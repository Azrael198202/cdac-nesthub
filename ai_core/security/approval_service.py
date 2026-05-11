from ai_core.config_loader import ConfigLoader


class ApprovalService:
    def __init__(self, config_root: str = "configs"):
        self.loader = ConfigLoader(config_root)

    def required(self, action: str) -> bool:
        cfg = self.loader.load("security/approval.yaml")
        return cfg.get("approval_rules", {}).get(action, False)

class RiskControl:
    def level(self, action: str) -> str:
        if action in {"shell_execution", "delete_file", "external_api_payment"}:
            return "high"
        return "low"

class CapabilityExpander:
    def expand(self, capabilities: list[str], feedback: dict) -> list[str]:
        if feedback.get("need_research") and "research" not in capabilities:
            return [*capabilities, "research"]
        return capabilities

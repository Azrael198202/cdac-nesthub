from __future__ import annotations

from ai_core.config_loader import ConfigLoader


class ToolRegistry:
    def __init__(self, config_root: str = "configs"):
        self.loader = ConfigLoader(config_root)

    def enabled_tools(self) -> dict:
        tools = self.loader.load("tools/tools.yaml")
        return {name: cfg for name, cfg in tools.items() if cfg.get("enabled", True)}

from __future__ import annotations

from ai_core.config_loader import ConfigLoader


class CapabilityRouter:
    def __init__(self, config_root: str = "configs"):
        self.loader = ConfigLoader(config_root)

    def capabilities_for(self, task_name: str) -> list[str]:
        mapping = self.loader.load("capabilities/task_capability_map.yaml")
        return mapping.get(task_name, [])

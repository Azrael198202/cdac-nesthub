from __future__ import annotations

from ai_core.config_loader import ConfigLoader


class ModelRouter:
    def __init__(self, config_root: str = "configs"):
        self.loader = ConfigLoader(config_root)

    def resolve(self, node: dict) -> dict:
        groups = self.loader.load("models/model_groups.yaml")
        group_name = node.get("model_group", "execution_models")
        return groups.get(group_name, {}).get("primary", {})

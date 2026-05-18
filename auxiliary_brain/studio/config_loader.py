from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class StudioCommandConfig:
    """Loads runtime-facing command phrases from configuration.

    The source code keeps only generic action identifiers. Human-facing phrases
    are stored in a config file so deployments can replace them without code
    changes.
    """

    def __init__(self, config_path: str | Path = "configs/agent_studio_commands.json") -> None:
        self.config_path = Path(config_path)

    def load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {"actions": [], "fallback_action": "create_participant"}
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def detect_action(self, message: str) -> str:
        payload = self.load()
        normalized = message.casefold()
        for item in payload.get("actions", []):
            for pattern in item.get("patterns", []):
                if str(pattern).casefold() in normalized:
                    return str(item.get("action"))
        return str(payload.get("fallback_action") or "create_participant")

    def action_profile(self, action: str) -> dict[str, Any]:
        payload = self.load()
        for item in payload.get("actions", []):
            if item.get("action") == action:
                return dict(item)
        return {}

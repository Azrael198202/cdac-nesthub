from __future__ import annotations

from ai_core.config.io import read_yaml, write_yaml
from ai_core.config.paths import RUNTIME_TOOLS_DIR


class ToolRegistry:
    def __init__(self) -> None:
        self.tools_file = RUNTIME_TOOLS_DIR / "tools.yaml"

    def ensure_default_tools(self) -> None:
        if self.tools_file.exists():
            return
        write_yaml(self.tools_file, {
            "tools": {
                "weather_forecast": {"type": "builtin", "approval_required": False},
                "flight_search": {"type": "builtin", "approval_required": False},
                "flight_booking_mock": {"type": "builtin", "approval_required": True},
                "web_search": {"type": "builtin", "approval_required": False},
            }
        })

    def get(self, name: str) -> dict:
        self.ensure_default_tools()
        data = read_yaml(self.tools_file, {"tools": {}})
        return data.get("tools", {}).get(name, {})

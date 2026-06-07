from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED


class MCPRegistry:
    """Generic MCP capability manifest registry.

    MCP is preserved as a first-class source. The registry reads static config and
    runtime-generated manifests but never embeds business-domain behavior.
    """

    STATIC_PATH = CONFIGS_DIR / "mcp_capability_registry.json"
    GENERATED_PATH = RUNTIME_GENERATED / "mcp" / "capability_registry.json"

    def load(self) -> dict[str, Any]:
        merged: dict[str, Any] = {"servers": [], "capabilities": []}
        for path in (self.STATIC_PATH, self.GENERATED_PATH):
            data = self._load(path)
            if not data:
                continue
            for key in ("servers", "capabilities"):
                values = data.get(key)
                if isinstance(values, list):
                    merged.setdefault(key, []).extend(values)
        return merged

    def find_capability(self, capability: str) -> dict[str, Any] | None:
        text = str(capability or "").casefold()
        for item in self.load().get("capabilities", []):
            if not isinstance(item, dict):
                continue
            names = [item.get("id"), item.get("name"), *(item.get("aliases") or [])]
            if any(str(name).casefold() == text for name in names if name):
                return item
        return None

    def _load(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

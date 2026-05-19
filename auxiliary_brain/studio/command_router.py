from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RoutedCommand:
    action: str
    name: str | None
    payload: str


class StudioCommandRouter:
    """Configuration-backed command router for studio instructions."""

    def __init__(self, config_path: str | Path = "configs/agent_studio_commands.json") -> None:
        self.config_path = Path(config_path)
        self.config = self._load_config()

    def route(self, message: str) -> RoutedCommand:
        text = message.strip()
        lowered = text.lower()
        phrases = self.config.get("command_phrases", {})
        if self._matches(lowered, phrases.get("execute_task", [])):
            return RoutedCommand("execute_task", self._extract_execute_name(text), text)
        if self._matches(lowered, phrases.get("feedback_adaptation", [])):
            return RoutedCommand("feedback_adaptation", self._extract_feedback_target(text), text)
        if self._matches(lowered, phrases.get("create_task", [])):
            return RoutedCommand("create_task", self._extract_named_value(text), text)
        if self._matches(lowered, phrases.get("create_participant", [])):
            return RoutedCommand("create_participant", self._extract_named_value(text), text)
        return RoutedCommand("chat", None, text)

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            return {
                "command_phrases": {
                    "create_participant": ["create an agent", "create a participant"],
                    "create_task": ["create a task"],
                    "execute_task": ["execute"],
                }
            }
        try:
            loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    def _matches(self, lowered: str, options: list[str]) -> bool:
        return any(str(option).lower() in lowered for option in options)

    def _extract_named_value(self, text: str) -> str | None:
        patterns = [
            r"\bnamed\s+([A-Za-z0-9_\- ]+?)(?:\s+to\s+|\s+which\s+|\s*,|\.|$)",
            r"\bname\s+([A-Za-z0-9_\- ]+?)(?:\s+to\s+|\s+which\s+|\s*,|\.|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                return name or None
        return None

    def _extract_execute_name(self, text: str) -> str | None:
        parts = text.strip().split()
        if len(parts) >= 2:
            return parts[-1].strip(" .,:;\"'") or None
        return self._extract_named_value(text)

    def _extract_feedback_target(self, text: str) -> str | None:
        # Generic compact identifier extraction for feedback messages.
        # Preserve compact identifiers such as "taskA" as one token.
        patterns = [
            r"\b((?:task|job|run)[A-Za-z0-9_\-]+)\b",
            r"\b(?:task|job|run)\s*[:=#-]\s*([A-Za-z0-9_\-]+)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip() or None
        return None

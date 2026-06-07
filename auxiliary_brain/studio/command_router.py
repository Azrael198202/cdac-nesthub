from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ai_core.commands import CommandSetService


@dataclass
class RoutedCommand:
    action: str
    name: str | None
    payload: str


class StudioCommandRouter:
    """Configuration-backed command router for studio instructions."""

    def __init__(self, config_path: str | Path = "configs/agent_studio_commands.json") -> None:
        self.config_path = Path(config_path)
        self.command_set_service = CommandSetService(default_path=self.config_path)
        self.config = self._load_config()

    def route(self, message: str) -> RoutedCommand:
        """Route user text through the effective command registry.

        commands[] is the source of truth.  This avoids spreading command phrase
        if/else checks across Studio code.  Runtime command-set overlays can add
        or disable commands without changing this router.
        """
        text = message.strip()
        lowered = text.lower()
        matched = self._match_registry(lowered)
        if matched:
            action = str(matched.get("action") or matched.get("command_id") or "chat")
            name = self._extract_name_for_action(action, text)
            return RoutedCommand(action, name, text)
        return RoutedCommand("chat", None, text)

    def _load_config(self) -> dict:
        return self.command_set_service.get_effective()

    def reload(self) -> None:
        self.config = self._load_config()

    def _registry(self) -> list[dict]:
        try:
            return self.command_set_service._normalize_registry(self.config)
        except Exception:
            return []

    def _match_registry(self, lowered: str) -> dict | None:
        for entry in self._registry():
            if not bool(entry.get("enabled", True)):
                continue
            if self._matches(lowered, entry.get("patterns", [])):
                return entry
        return None

    def _extract_name_for_action(self, action: str, text: str) -> str | None:
        if action == "execute_task":
            return self._extract_execute_name(text)
        if action == "feedback_adaptation":
            return self._extract_feedback_target(text)
        if action in {"create_task", "create_participant", "update_participant", "delete_participant"}:
            return self._extract_named_value(text)
        return self._extract_named_value(text)

    def _matches(self, lowered: str, options: list[str]) -> bool:
        for option in options:
            phrase = str(option).lower().strip()
            if not phrase:
                continue
            # Single-word management verbs are only commands when they appear at
            # the beginning of the message. This keeps normal conversation from
            # being accidentally routed into task execution.
            if " " not in phrase:
                if lowered == phrase or lowered.startswith(phrase + " "):
                    return True
                continue
            if phrase in lowered:
                return True
        return False

    def _extract_named_value(self, text: str) -> str | None:
        # Prefer quoted names so commands such as
        # preserve the user-visible identity exactly.
        quoted_patterns = [
            r"\bnamed\s+[\"']([^\"']+)[\"']",
            r"\bname\s+[\"']([^\"']+)[\"']",
        ]
        for pattern in quoted_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                return name or None

        patterns = [
            r"\bnamed\s+([A-Za-z0-9_\- ]+?)(?:\s+to\s+|\s+that\s+|\s+which\s+|\s+who\s+|\s+can\s+|\s*,|\.|$)",
            r"\bname\s+([A-Za-z0-9_\- ]+?)(?:\s+to\s+|\s+that\s+|\s+which\s+|\s+who\s+|\s+can\s+|\s*,|\.|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                name = match.group(1).strip().strip("\"'")
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

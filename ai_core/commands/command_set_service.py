from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .default_command_set import default_command_set


class CommandSetService:
    """Manage default and runtime-customized Studio command sets.

    The source default is immutable at runtime. User customization is saved under
    runtime/configs so it can be changed without modifying ai_core source files.
    This service intentionally handles only command metadata and phrase routing;
    it does not contain task/business logic.
    """

    def __init__(
        self,
        default_path: str | Path = "configs/agent_studio_commands.json",
        runtime_path: str | Path = "runtime/configs/agent_studio_commands.runtime.json",
    ) -> None:
        self.default_path = Path(default_path)
        self.runtime_path = Path(runtime_path)

    def get_default(self) -> dict[str, Any]:
        loaded = self._read_json(self.default_path)
        if not loaded:
            return default_command_set()
        base = default_command_set()
        return self._merge(base, loaded)

    def get_runtime_override(self) -> dict[str, Any]:
        return self._read_json(self.runtime_path) or {}

    def get_effective(self) -> dict[str, Any]:
        effective = self.get_default()
        return self._merge(effective, self.get_runtime_override())

    def list_commands(self) -> dict[str, Any]:
        effective = self.get_effective()
        return {
            "ok": True,
            "status": "completed",
            "command_set": effective,
            "command_registry": self._normalize_registry(effective),
            "default_path": str(self.default_path),
            "runtime_override_path": str(self.runtime_path),
        }

    def update_runtime(self, update: dict[str, Any]) -> dict[str, Any]:
        update = self._migrate_legacy_update(update or {})
        current = self.get_runtime_override()
        merged = self._merge(current, update)
        self.runtime_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "status": "completed",
            "message": "Runtime command set was updated.",
            "runtime_override": merged,
            "effective_command_set": self.get_effective(),
            "path": str(self.runtime_path),
        }

    def update_from_instruction(self, instruction: str) -> dict[str, Any]:
        """Apply a small generic instruction grammar for command-set changes.

        Supported stable forms:
        - add phrase "..." to <command_key>
        - remove phrase "..." from <command_key>
        - set <command_key> phrases to ["...", "..."]

        More complex natural-language customization can be routed to AI Core by
        calling this method with structured JSON in the message body.
        """
        text = str(instruction or "").strip()
        parsed_json = self._extract_json_object(text)
        if parsed_json:
            return self.update_runtime(parsed_json)

        add_command = re.search(r"\badd\s+command\s+[\"']([^\"']+)[\"']\s+as\s+([A-Za-z0-9_\-]+)", text, flags=re.I)
        if add_command:
            phrase = add_command.group(1).strip()
            action = add_command.group(2).strip()
            return self._add_command(action, [phrase])

        add = re.search(r"\badd\s+phrase\s+[\"']([^\"']+)[\"']\s+to\s+([A-Za-z0-9_\-]+)", text, flags=re.I)
        if add:
            phrase = add.group(1).strip()
            key = add.group(2).strip()
            return self._add_phrase(key, phrase)

        remove = re.search(r"\bremove\s+phrase\s+[\"']([^\"']+)[\"']\s+from\s+([A-Za-z0-9_\-]+)", text, flags=re.I)
        if remove:
            phrase = remove.group(1).strip()
            key = remove.group(2).strip()
            return self._remove_phrase(key, phrase)

        return {
            "ok": False,
            "status": "requires_input",
            "message": "Please specify the command registry change, for example: add phrase \"make agent\" to create_participant, or provide JSON with a commands[] registry update.",
            "interaction_request": {
                "type": "command_registry_update",
                "kind": "command_registry_update",
                "fields": [
                    {
                        "field": "command_registry_update_json",
                        "label": "Command registry update JSON",
                        "input_type": "textarea",
                        "required": True,
                        "placeholder": '{"commands":[{"command_id":"create_participant","action":"create_participant","patterns":["make agent"],"enabled":true,"priority":100}]}',
                    }
                ],
            },
        }

    def _add_command(self, action: str, patterns: list[str]) -> dict[str, Any]:
        override = self.get_runtime_override()
        commands = override.setdefault("commands", [])
        if not isinstance(commands, list):
            commands = []
            override["commands"] = commands
        command_id = action.strip()
        found = None
        for item in commands:
            if isinstance(item, dict) and str(item.get("command_id") or item.get("action")) == command_id:
                found = item
                break
        if found is None:
            found = {"command_id": command_id, "action": command_id, "enabled": True, "priority": 100, "patterns": []}
            commands.append(found)
        values = found.setdefault("patterns", [])
        if not isinstance(values, list):
            values = []
            found["patterns"] = values
        for phrase in patterns:
            phrase = str(phrase).strip()
            if phrase and phrase not in values:
                values.append(phrase)
        return self.update_runtime(override)

    def _add_phrase(self, command_key: str, phrase: str) -> dict[str, Any]:
        override = self.get_runtime_override()
        commands = override.setdefault("commands", [])
        if not isinstance(commands, list):
            commands = []
            override["commands"] = commands
        target = None
        for item in commands:
            if isinstance(item, dict) and str(item.get("command_id") or item.get("action")) == command_key:
                target = item
                break
        if target is None:
            target = {
                "command_id": command_key,
                "action": command_key,
                "category": "custom",
                "enabled": True,
                "priority": 100,
                "patterns": [],
            }
            commands.append(target)
        patterns = target.setdefault("patterns", [])
        if not isinstance(patterns, list):
            patterns = []
            target["patterns"] = patterns
        phrase = str(phrase or "").strip()
        if phrase and phrase not in patterns:
            patterns.append(phrase)
        return self.update_runtime(override)

    def _remove_phrase(self, command_key: str, phrase: str) -> dict[str, Any]:
        override = self.get_runtime_override()
        commands = override.setdefault("commands", [])
        if isinstance(commands, list):
            for item in commands:
                if isinstance(item, dict) and str(item.get("command_id") or item.get("action")) == command_key:
                    patterns = item.get("patterns", [])
                    if isinstance(patterns, list):
                        item["patterns"] = [value for value in patterns if str(value) != str(phrase)]
                    break
        return self.update_runtime(override)


    def get_registry(self) -> list[dict[str, Any]]:
        """Return normalized command registry entries sorted by priority.

        commands[] is the only routing source of truth.  Older command_phrases
        payloads are accepted only by update_runtime() as migration input and are
        converted into commands[] before persistence.
        """
        return self._normalize_registry(self.get_effective())

    def _normalize_registry(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        raw_commands = config.get("commands")
        if isinstance(raw_commands, list):
            for raw in raw_commands:
                if not isinstance(raw, dict):
                    continue
                command_id = str(raw.get("command_id") or raw.get("id") or raw.get("action") or "").strip()
                action = str(raw.get("action") or command_id).strip()
                if not command_id or not action:
                    continue
                patterns = raw.get("patterns") or raw.get("phrases") or []
                if isinstance(patterns, str):
                    patterns = [patterns]
                patterns = [str(item).strip() for item in patterns if str(item).strip()]
                if not patterns:
                    continue
                entry = dict(raw)
                entry["command_id"] = command_id
                entry["action"] = action
                entry["patterns"] = patterns
                entry["enabled"] = bool(entry.get("enabled", True))
                try:
                    entry["priority"] = int(entry.get("priority", 0) or 0)
                except Exception:
                    entry["priority"] = 0
                entries.append(entry)
                seen.add(command_id)

        entries.sort(key=lambda item: int(item.get("priority", 0) or 0), reverse=True)
        return entries

    def _migrate_legacy_update(self, update: dict[str, Any]) -> dict[str, Any]:
        """Convert legacy command_phrases payloads into commands[] entries.

        This keeps old clients working while ensuring persisted runtime config and
        routing remain registry-driven.
        """
        if not isinstance(update, dict):
            return {}
        converted = deepcopy(update)
        legacy = converted.pop("command_phrases", None)
        if isinstance(legacy, dict):
            commands = converted.setdefault("commands", [])
            if not isinstance(commands, list):
                commands = []
                converted["commands"] = commands
            for key, patterns in legacy.items():
                command_id = str(key or "").strip()
                if not command_id:
                    continue
                if isinstance(patterns, str):
                    patterns = [patterns]
                if not isinstance(patterns, list):
                    continue
                clean_patterns = [str(item).strip() for item in patterns if str(item).strip()]
                if not clean_patterns:
                    continue
                existing = None
                for item in commands:
                    if isinstance(item, dict) and str(item.get("command_id") or item.get("action")) == command_id:
                        existing = item
                        break
                if existing is None:
                    existing = {
                        "command_id": command_id,
                        "action": command_id,
                        "category": "custom",
                        "enabled": True,
                        "priority": 100,
                        "patterns": [],
                    }
                    commands.append(existing)
                values = existing.setdefault("patterns", [])
                if not isinstance(values, list):
                    values = []
                    existing["patterns"] = values
                for phrase in clean_patterns:
                    if phrase not in values:
                        values.append(phrase)
        return converted

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
        return {}

    def _merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(base)
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._merge(result[key], value)
            elif isinstance(value, list) and isinstance(result.get(key), list):
                combined = list(result.get(key) or [])
                for item in value:
                    if item not in combined:
                        combined.append(item)
                result[key] = combined
            else:
                result[key] = deepcopy(value)
        return result

    def _extract_json_object(self, text: str) -> dict[str, Any] | None:
        stripped = text.strip()
        candidates = []
        if stripped.startswith("{") and stripped.endswith("}"):
            candidates.append(stripped)
        match = re.search(r"(\{.*\})", stripped, flags=re.DOTALL)
        if match:
            candidates.append(match.group(1))
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        return None

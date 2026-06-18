from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_DIR


class RuntimeApprovalPolicyStore:
    """Generic persistent approval policy store for runtime-registered operations.

    This store is deliberately capability-agnostic. It does not know what a tool
    does; it only stores whether a registered tool/profile should ask for
    approval every time, once, or never.  The executable tool still owns its own
    validation and execution logic.
    """

    VALID_MODES = {"always", "once", "never"}

    def __init__(self, *, path: Path | None = None) -> None:
        self.path = path or (RUNTIME_DIR / "configs" / "policies" / "runtime_approval_policy.json")

    def get_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "tools": {}, "updated_at": None}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return {"version": 1, "tools": {}, "updated_at": None}
        return data if isinstance(data, dict) else {"version": 1, "tools": {}, "updated_at": None}

    def set_tool_policy(self, *, tool_id: str, profile_id: str = "default", mode: str = "always") -> dict[str, Any]:
        clean_tool = self._safe(tool_id, "tool")
        clean_profile = self._safe(profile_id, "default")
        clean_mode = str(mode or "always").strip().lower()
        if clean_mode not in self.VALID_MODES:
            clean_mode = "always"
        state = self.get_state()
        tools = state.setdefault("tools", {})
        if not isinstance(tools, dict):
            tools = {}
            state["tools"] = tools
        profiles = tools.setdefault(clean_tool, {})
        if not isinstance(profiles, dict):
            profiles = {}
            tools[clean_tool] = profiles
        entry = profiles.setdefault(clean_profile, {})
        if not isinstance(entry, dict):
            entry = {}
            profiles[clean_profile] = entry
        entry.update({
            "mode": clean_mode,
            "trusted": bool(entry.get("trusted")) if clean_mode == "once" else False,
            "updated_at": self._now(),
        })
        state["updated_at"] = self._now()
        self._write(state)
        return self.get_tool_policy(tool_id=clean_tool, profile_id=clean_profile)

    def get_tool_policy(self, *, tool_id: str, profile_id: str = "default") -> dict[str, Any]:
        clean_tool = self._safe(tool_id, "tool")
        clean_profile = self._safe(profile_id, "default")
        state = self.get_state()
        tools = state.get("tools") if isinstance(state.get("tools"), dict) else {}
        profiles = tools.get(clean_tool) if isinstance(tools, dict) else {}
        entry = profiles.get(clean_profile) if isinstance(profiles, dict) else None
        if not isinstance(entry, dict):
            return {
                "tool_id": clean_tool,
                "profile_id": clean_profile,
                "mode": None,
                "trusted": False,
                "explicit": False,
            }
        mode = str(entry.get("mode") or "always").strip().lower()
        if mode not in self.VALID_MODES:
            mode = "always"
        return {
            "tool_id": clean_tool,
            "profile_id": clean_profile,
            "mode": mode,
            "trusted": bool(entry.get("trusted")),
            "explicit": True,
            "updated_at": entry.get("updated_at"),
            "trusted_at": entry.get("trusted_at"),
        }

    def list_policies(self) -> list[dict[str, Any]]:
        state = self.get_state()
        out: list[dict[str, Any]] = []
        tools = state.get("tools") if isinstance(state.get("tools"), dict) else {}
        for tool_id, profiles in tools.items():
            if not isinstance(profiles, dict):
                continue
            for profile_id, entry in profiles.items():
                if isinstance(entry, dict):
                    out.append(self.get_tool_policy(tool_id=str(tool_id), profile_id=str(profile_id)))
        out.sort(key=lambda item: (str(item.get("tool_id") or ""), str(item.get("profile_id") or "")))
        return out

    def is_auto_approved(self, *, tool_id: str, profile_id: str = "default") -> bool:
        policy = self.get_tool_policy(tool_id=tool_id, profile_id=profile_id)
        mode = str(policy.get("mode") or "").lower()
        if mode == "never":
            return True
        if mode == "once" and bool(policy.get("trusted")):
            return True
        return False

    def record_confirmation(self, *, tool_id: str, profile_id: str = "default", remember: bool = False) -> dict[str, Any]:
        clean_tool = self._safe(tool_id, "tool")
        clean_profile = self._safe(profile_id, "default")
        state = self.get_state()
        tools = state.setdefault("tools", {})
        if not isinstance(tools, dict):
            tools = {}
            state["tools"] = tools
        profiles = tools.setdefault(clean_tool, {})
        if not isinstance(profiles, dict):
            profiles = {}
            tools[clean_tool] = profiles
        entry = profiles.setdefault(clean_profile, {})
        if not isinstance(entry, dict):
            entry = {}
            profiles[clean_profile] = entry
        mode = str(entry.get("mode") or "always").lower()
        if mode not in self.VALID_MODES:
            mode = "always"
        if remember:
            mode = "once"
            entry["trusted"] = True
            entry["trusted_at"] = self._now()
        elif mode == "once" and not entry.get("trusted"):
            entry["trusted"] = True
            entry["trusted_at"] = self._now()
        entry["mode"] = mode
        entry["last_confirmed_at"] = self._now()
        entry["updated_at"] = self._now()
        state["updated_at"] = self._now()
        self._write(state)
        return self.get_tool_policy(tool_id=clean_tool, profile_id=clean_profile)

    def _write(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _safe(self, value: str | None, fallback: str) -> str:
        raw = str(value or "").strip() or fallback
        return "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in raw).strip("_") or fallback

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

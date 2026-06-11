from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import PROJECT_ROOT


class OperationPromptProfileRouter:
    """Select small operation-scoped prompt guidance from runtime contracts.

    The router is domain-neutral.  It does not look for task topics.  It uses
    stage ids, execution methods, capability flags, and source/evidence
    contracts to keep prompts from mixing retrieval, writing, creation, and
    execution responsibilities.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or PROJECT_ROOT / "runtime/configs/prompts/operation_prompt_profiles.json")
        self._cache: dict[str, Any] | None = None

    def profile_for(self, *, node_id: str | None, state: dict[str, Any], adapter: dict[str, Any] | None = None) -> dict[str, Any]:
        profiles = self._profiles()
        key = self._profile_key(node_id=node_id, state=state, adapter=adapter or {})
        profile = profiles.get(key) or profiles.get("general_json_planning") or {}
        return {"profile_id": key if key in profiles else "general_json_planning", **profile}

    def render_addendum(self, profile: dict[str, Any]) -> str:
        if not isinstance(profile, dict):
            return ""
        rules = profile.get("rules") if isinstance(profile.get("rules"), list) else []
        purpose = str(profile.get("purpose") or "").strip()
        profile_id = str(profile.get("profile_id") or "").strip()
        lines = []
        if profile_id:
            lines.append(f"Operation profile: {profile_id}")
        if purpose:
            lines.append(f"Purpose: {purpose}")
        if rules:
            lines.append("Rules:")
            lines.extend(f"- {str(rule)}" for rule in rules if str(rule).strip())
        return "\n".join(lines).strip()

    def _profiles(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        profiles = data.get("profiles") if isinstance(data, dict) else {}
        self._cache = profiles if isinstance(profiles, dict) else {}
        return self._cache

    def _profile_key(self, *, node_id: str | None, state: dict[str, Any], adapter: dict[str, Any]) -> str:
        node = str(node_id or "").casefold()
        if "capability" in node and ("acquisition" in node or "gap" in node):
            return "capability_acquisition"
        if self._contains_method(state, {"registered_tool", "existing_tool", "tool_execution"}):
            return "capability_execution"
        if self._requires_source_material(state):
            return "source_retrieval"
        if "planning" in node or "workflow" in node:
            return "task_graph_compile"
        if self._contains_method(state, {"content_generation", "static_response"}):
            return "document_composition"
        role = str(adapter.get("runtime_role") or adapter.get("role_id") or "").casefold()
        if "code" in role or "capability" in role:
            return "capability_acquisition"
        return "general_json_planning"

    def _requires_source_material(self, value: Any, depth: int = 0) -> bool:
        if depth > 8:
            return False
        if isinstance(value, dict):
            if value.get("requires_source_material") is True or value.get("requires_live_evidence") is True:
                return True
            if value.get("evidence_required") is True or value.get("needs_web_search") is True:
                return True
            method = str(value.get("execution_method") or value.get("selected_execution_method") or value.get("action_type") or "").strip()
            if method in {"web_query", "web_search"}:
                return True
            return any(self._requires_source_material(v, depth + 1) for v in value.values())
        if isinstance(value, list):
            return any(self._requires_source_material(v, depth + 1) for v in value[:80])
        return False

    def _contains_method(self, value: Any, methods: set[str], depth: int = 0) -> bool:
        if depth > 8:
            return False
        if isinstance(value, dict):
            current = str(value.get("execution_method") or value.get("action_type") or value.get("capability_type") or "").strip()
            if current in methods:
                return True
            return any(self._contains_method(v, methods, depth + 1) for v in value.values())
        if isinstance(value, list):
            return any(self._contains_method(v, methods, depth + 1) for v in value[:80])
        return False

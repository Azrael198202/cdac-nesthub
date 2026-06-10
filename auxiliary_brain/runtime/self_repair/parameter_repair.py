from __future__ import annotations

import difflib
from typing import Any

from .contracts import RepairAction


class ParameterBindingRepairer:
    """Repairs generic parameter binding gaps using declared aliases and names.

    The repairer does not contain task-specific synonym lists. It can use aliases
    declared by runtime artifacts, exact normalized matches, and conservative
    string similarity to map already-provided values into required fields.
    """

    def plan(
        self,
        *,
        provided: dict[str, Any],
        required: list[str],
        aliases: dict[str, list[str]] | None = None,
    ) -> list[RepairAction]:
        if not isinstance(provided, dict) or not isinstance(required, list):
            return []
        aliases = aliases if isinstance(aliases, dict) else {}
        actions: list[RepairAction] = []
        normalized = {self._norm(k): k for k in provided.keys()}
        for target in required:
            if target in provided and provided.get(target) not in (None, ""):
                continue
            source_key = self._find_source(target, provided, normalized, aliases)
            if source_key:
                actions.append(RepairAction(
                    action_type="parameter_alias_binding",
                    level="deterministic",
                    description=f"Bind provided parameter '{source_key}' to required parameter '{target}'.",
                    target_path=target,
                    before=None,
                    after=provided.get(source_key),
                    safe_to_apply=True,
                    requires_validation=True,
                    confidence=0.86,
                    metadata={"source_key": source_key},
                ))
        return actions

    def apply(self, *, provided: dict[str, Any], actions: list[RepairAction]) -> dict[str, Any]:
        out = dict(provided or {})
        for action in actions:
            if action.action_type == "parameter_alias_binding" and action.target_path:
                out[action.target_path] = action.after
        return out

    def _find_source(self, target: str, provided: dict[str, Any], normalized: dict[str, str], aliases: dict[str, list[str]]) -> str:
        target_norm = self._norm(target)
        if target_norm in normalized:
            return normalized[target_norm]
        for alias in aliases.get(target, []) or []:
            alias_norm = self._norm(str(alias))
            if alias_norm in normalized:
                return normalized[alias_norm]
        candidates = list(provided.keys())
        matches = difflib.get_close_matches(target_norm, [self._norm(x) for x in candidates], n=1, cutoff=0.82)
        if matches:
            return normalized[matches[0]]
        return ""

    def _norm(self, value: str) -> str:
        return "".join(ch for ch in str(value).casefold() if ch.isalnum())

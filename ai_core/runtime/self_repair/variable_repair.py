from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .contracts import RepairAction
from .json_path import get_path

_VAR_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


class VariableBindingRepairer:
    """Resolves template references from generic runtime state."""

    def plan(self, *, payload: dict[str, Any], runtime_state: dict[str, Any]) -> list[RepairAction]:
        actions: list[RepairAction] = []
        for path, value in self._walk(payload):
            if isinstance(value, str) and "{{" in value and "}}" in value:
                repaired, unresolved = self._resolve_text(value, runtime_state)
                if repaired != value:
                    actions.append(RepairAction(
                        action_type="variable_binding_resolution",
                        level="deterministic",
                        description=f"Resolve template variables at '{path}'.",
                        target_path=path,
                        before=value,
                        after=repaired,
                        safe_to_apply=True,
                        requires_validation=True,
                        confidence=0.9 if not unresolved else 0.72,
                        metadata={"unresolved": unresolved},
                    ))
        return actions

    def apply(self, *, payload: dict[str, Any], actions: list[RepairAction]) -> dict[str, Any]:
        out = deepcopy(payload)
        for action in actions:
            if action.action_type == "variable_binding_resolution":
                self._set(out, action.target_path, action.after)
        return out

    def _resolve_text(self, text: str, state: dict[str, Any]) -> tuple[str, list[str]]:
        unresolved: list[str] = []

        def repl(match: re.Match[str]) -> str:
            expr = match.group(1).strip()
            value = self._lookup(expr, state)
            if value is None:
                unresolved.append(expr)
                return match.group(0)
            if isinstance(value, (dict, list)):
                return self._compact(value)
            return str(value)

        return _VAR_RE.sub(repl, text), unresolved

    def _lookup(self, expr: str, state: dict[str, Any]) -> Any:
        paths = [expr]
        if expr.startswith("Step") and "." in expr:
            step_name, rest = expr.split(".", 1)
            paths.extend([
                f"steps.{step_name}.{rest}",
                f"step_outputs.{step_name}.{rest}",
                f"outputs.{step_name}.{rest}",
            ])
        for path in paths:
            value = get_path(state, path, None)
            if value is not None:
                return value
        return None

    def _walk(self, value: Any, prefix: str = ""):
        if isinstance(value, dict):
            for k, v in value.items():
                path = f"{prefix}.{k}" if prefix else str(k)
                yield from self._walk(v, path)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                path = f"{prefix}.{i}" if prefix else str(i)
                yield from self._walk(v, path)
        else:
            yield prefix, value

    def _set(self, data: Any, path: str, value: Any) -> None:
        parts = path.split(".") if path else []
        cur = data
        for part in parts[:-1]:
            if isinstance(cur, dict):
                cur = cur.setdefault(part, {})
            elif isinstance(cur, list) and part.isdigit():
                cur = cur[int(part)]
            else:
                return
        if not parts:
            return
        last = parts[-1]
        if isinstance(cur, dict):
            cur[last] = value
        elif isinstance(cur, list) and last.isdigit() and int(last) < len(cur):
            cur[int(last)] = value

    def _compact(self, value: Any) -> str:
        if isinstance(value, list):
            return "\n".join(str(x) for x in value)
        if isinstance(value, dict):
            return "\n".join(f"{k}: {v}" for k, v in value.items())
        return str(value)

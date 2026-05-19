from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED
from ai_core.runtime.capability.source_priority_engine import SourcePriorityEngine


class ExecutionModeSelector:
    """Selects source mode from runtime/config contracts.

    Business/task vocabulary is not embedded in source code.  Optional routing
    indicators live in JSON policy files and runtime-generated contracts.
    """

    def __init__(self) -> None:
        self.priority = SourcePriorityEngine()

    def select(self, *, step: dict[str, Any], plan: dict[str, Any], state: dict[str, Any], capability: str) -> str:
        policy = self.policy_for(step=step, plan=plan, state=state, capability=capability)
        explicit = self._explicit_mode(step, plan, state)
        if explicit:
            return explicit
        text = self._contract_text([step, plan, state.get("runtime_request_semantics"), capability])
        for rule in policy.get("routing_rules", []):
            if not isinstance(rule, dict):
                continue
            indicators = [str(x).casefold() for x in rule.get("indicators", []) if str(x).strip()]
            if indicators and any(item in text for item in indicators):
                mode = str(rule.get("execution_mode") or "").strip()
                if mode:
                    return mode
        # Default to the first non-runtime-native mode unless runtime-native is
        # explicitly requested by contract or routing rule. This prevents local
        # runtime state from swallowing external or generated capabilities.
        for mode in self.priority.order(policy):
            if mode != "runtime_native":
                return mode
        return self.priority.order(policy)[0]

    def policy_for(self, *, step: dict[str, Any], plan: dict[str, Any], state: dict[str, Any], capability: str) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for data in self._load_policy_files():
            merged = self._merge(merged, data)
        for obj in (state, state.get("runtime") if isinstance(state, dict) else None, plan, step):
            if isinstance(obj, dict):
                for key in ("capability_policy", "execution_source_policy", "source_policy"):
                    if isinstance(obj.get(key), dict):
                        merged = self._merge(merged, obj[key])
        return merged

    def _explicit_mode(self, *items: Any) -> str:
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("execution_mode", "source_level", "required_source_level"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            strategy = item.get("execution_strategy")
            if isinstance(strategy, list):
                for value in strategy:
                    text = str(value).strip()
                    if text in {"runtime_native", "structured_provider", "web_retrieval"}:
                        return text
        return ""

    def _load_policy_files(self) -> list[dict[str, Any]]:
        paths = [
            CONFIGS_DIR / "runtime_capability_policy.json",
            RUNTIME_GENERATED / "contracts" / "runtime_capability_policy.json",
        ]
        result = []
        for path in paths:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict):
                result.append(data)
        return result

    def _merge(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        result = dict(left)
        for key, value in right.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._merge(result[key], value)
            elif isinstance(value, list) and isinstance(result.get(key), list):
                result[key] = [*result[key], *value]
            else:
                result[key] = value
        return result

    def _contract_text(self, values: list[Any]) -> str:
        parts: list[str] = []
        def walk(value: Any) -> None:
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (int, float, bool)):
                parts.append(str(value))
            elif isinstance(value, dict):
                for k, v in value.items():
                    parts.append(str(k))
                    walk(v)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        for value in values:
            walk(value)
        return " ".join(parts).casefold()

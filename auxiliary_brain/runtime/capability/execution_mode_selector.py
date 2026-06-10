from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED
from auxiliary_brain.runtime.capability.source_priority_engine import SourcePriorityEngine
from auxiliary_brain.runtime.capability.semantic.semantic_capability_classifier import SemanticCapabilityClassifier


class ExecutionModeSelector:
    """Selects a generic execution source mode from runtime contracts.

    Design boundary:
    - ai_core owns only generic source-mode arbitration.
    - Workflow/planning contracts are treated as locked decisions when present.
    - Domain/task vocabulary belongs to runtime-generated contracts and config,
      not this source file.
    """

    METHOD_MODE_MAP = {
        "web_search": "web_retrieval",
        "api_call": "structured_provider",
        "knowledge_base": "runtime_native",
        "model_knowledge": "runtime_native",
        "content_generation": "runtime_native",
        "runtime_generated_tool": "runtime_native",
        "existing_tool": "runtime_native",
    }

    STRATEGY_MODE_MAP = {
        "web_evidence": "web_retrieval",
        "web_retrieval": "web_retrieval",
        "external_evidence": "web_retrieval",
        "structured_provider": "structured_provider",
        "api_call": "structured_provider",
        "runtime_native": "runtime_native",
        "local_knowledge": "runtime_native",
        "knowledge_base": "runtime_native",
    }

    def __init__(self) -> None:
        self.priority = SourcePriorityEngine()
        self.classifier = SemanticCapabilityClassifier()

    def select(self, *, step: dict[str, Any], plan: dict[str, Any], state: dict[str, Any], capability: str) -> str:
        policy = self.policy_for(step=step, plan=plan, state=state, capability=capability)
        strategy = self._strategy_values(step, plan, state)

        # 1) Respect locked workflow contracts first.  The execution layer must
        # not re-interpret a planning decision into another source family.
        locked_mode = self._locked_mode(step, plan, state)
        if locked_mode and self._mode_allowed(locked_mode, strategy, policy):
            return locked_mode

        # 2) Apply explicit source-mode contracts from planning/runtime policy.
        explicit = self._explicit_mode(step, plan, state)
        if explicit and self._mode_allowed(explicit, strategy, policy):
            return explicit

        # 3) Source-policy flags are generic and may require external evidence
        # even when the semantic classifier is uncertain.
        source_policy_mode = self._mode_from_source_policy(step, plan, state, policy)
        if source_policy_mode and self._mode_allowed(source_policy_mode, strategy, policy):
            return source_policy_mode

        # 4) Execution strategy is still a planning-owned hint and should be
        # evaluated before semantic text classification.
        strategy_mode = self._mode_from_strategy(strategy, policy)
        if strategy_mode and self._mode_allowed(strategy_mode, strategy, policy):
            return strategy_mode

        # 5) Semantic classification is a fallback, not an override of a locked
        # plan. It remains config/taxonomy driven.
        classification = self.classifier.classify(step=step, plan=plan, state=state, capability=capability)
        category = str(classification.get("category") or "")
        semantic_mode = self._mode_from_category(category, policy)
        if semantic_mode and self._mode_allowed(semantic_mode, strategy, policy):
            return semantic_mode

        text = self._contract_text([capability, step.get("step_type"), step.get("required_capability"), strategy])
        for rule in policy.get("routing_rules", []):
            if not isinstance(rule, dict):
                continue
            scope = str(rule.get("match_scope") or "capability_semantics")
            if scope not in {"capability_semantics", "execution_strategy"}:
                continue
            indicators = [str(x).casefold() for x in rule.get("indicators", []) if str(x).strip()]
            if indicators and any(item in text for item in indicators):
                mode = str(rule.get("execution_mode") or "").strip()
                if mode and self._mode_allowed(mode, strategy, policy):
                    return mode

        default = str(policy.get("unknown_capability_default") or "").strip()
        if default and self._mode_allowed(default, strategy, policy):
            return default
        for mode in self.priority.order(policy):
            if self._mode_allowed(mode, strategy, policy):
                return mode
        return self.priority.order(policy)[0]

    def _locked_mode(self, *items: Any) -> str:
        for item in items:
            if not isinstance(item, dict):
                continue
            method = str(item.get("execution_method") or "").strip()
            if method in self.METHOD_MODE_MAP:
                return self.METHOD_MODE_MAP[method]
            decision = item.get("execution_decision") if isinstance(item.get("execution_decision"), dict) else {}
            method = str(decision.get("execution_method") or decision.get("selected_method") or "").strip()
            if method in self.METHOD_MODE_MAP:
                return self.METHOD_MODE_MAP[method]
            steps = item.get("planned_steps")
            if isinstance(steps, list):
                for step in steps:
                    mode = self._locked_mode(step)
                    if mode:
                        return mode
        return ""

    def _mode_from_source_policy(self, *items: Any) -> str:
        policy = items[-1] if items and isinstance(items[-1], dict) else {}
        source_policies: list[dict[str, Any]] = []
        for item in items[:-1]:
            if not isinstance(item, dict):
                continue
            for key in ("source_policy", "execution_source_policy", "capability_policy"):
                value = item.get(key)
                if isinstance(value, dict):
                    source_policies.append(value)
            steps = item.get("planned_steps")
            if isinstance(steps, list):
                for step in steps:
                    if isinstance(step, dict):
                        for key in ("source_policy", "execution_source_policy", "capability_policy"):
                            value = step.get(key)
                            if isinstance(value, dict):
                                source_policies.append(value)
        for source_policy in source_policies:
            if source_policy.get("requires_live_evidence") or source_policy.get("allow_external") is True:
                preferred = source_policy.get("preferred_mode") or source_policy.get("execution_mode")
                if isinstance(preferred, str) and preferred.strip():
                    return preferred.strip()
                for mode in self.priority.order(policy):
                    if mode in {"structured_provider", "web_retrieval"}:
                        return mode
            if source_policy.get("allow_external") is False:
                return "runtime_native"
        return ""

    def _mode_from_strategy(self, strategy: list[str], policy: dict[str, Any]) -> str:
        normalized = {str(x).strip() for x in strategy if str(x).strip()}
        if not normalized:
            return ""
        for value in normalized:
            if value in self.STRATEGY_MODE_MAP:
                return self.STRATEGY_MODE_MAP[value]
        for rule in policy.get("routing_rules", []):
            if not isinstance(rule, dict):
                continue
            if str(rule.get("match_scope") or "") != "execution_strategy":
                continue
            values = {str(x).strip() for x in rule.get("strategy_values", []) if str(x).strip()}
            if values and normalized.intersection(values):
                return str(rule.get("execution_mode") or "").strip()
        return ""

    def _mode_allowed(self, mode: str, strategy: list[str], policy: dict[str, Any]) -> bool:
        return bool(mode) and not self._runtime_native_denied(mode, strategy, policy)

    def _runtime_native_denied(self, mode: str, strategy: list[str], policy: dict[str, Any]) -> bool:
        if mode != "runtime_native":
            return False
        strategy_set = {str(x).strip() for x in strategy if str(x).strip()}
        for rule in policy.get("deny_runtime_native_when", []):
            if not isinstance(rule, dict):
                continue
            values = {str(x).strip() for x in rule.get("execution_strategy_contains", []) if str(x).strip()}
            if values and strategy_set.intersection(values):
                return True
            required = {str(x).strip() for x in rule.get("source_required", []) if str(x).strip()}
            if required and strategy_set.intersection(required):
                return True
        return False

    def _strategy_values(self, *items: Any) -> list[str]:
        result: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            strategy = item.get("execution_strategy")
            if isinstance(strategy, list):
                result.extend(str(x).strip() for x in strategy if str(x).strip())
            method = item.get("execution_method")
            if isinstance(method, str) and method.strip():
                result.append(method.strip())
            steps = item.get("planned_steps")
            if isinstance(steps, list):
                for step in steps:
                    if isinstance(step, dict):
                        result.extend(self._strategy_values(step))
        return list(dict.fromkeys(result))

    def _mode_from_category(self, category: str, policy: dict[str, Any]) -> str:
        if not category:
            return ""
        for rule in policy.get("routing_rules", []):
            if not isinstance(rule, dict):
                continue
            categories = [str(x) for x in rule.get("semantic_categories", [])]
            if category in categories:
                mode = str(rule.get("execution_mode") or "").strip()
                if mode:
                    return mode
        graph = self.classifier._load_graph()
        node = graph.get(category) if isinstance(graph, dict) else None
        if isinstance(node, dict):
            modes = node.get("preferred_modes")
            if isinstance(modes, list) and modes:
                return str(modes[0])
        return ""

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

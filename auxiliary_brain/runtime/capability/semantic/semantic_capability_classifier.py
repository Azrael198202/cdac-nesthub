from __future__ import annotations

import json
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED


class SemanticCapabilityClassifier:
    """Classifies a capability into generic source categories.

    The classifier is contract/config driven. Core code only understands generic
    categories, not business domains.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()

    def classify(self, *, step: dict[str, Any], plan: dict[str, Any], state: dict[str, Any], capability: str) -> dict[str, Any]:
        explicit = self._explicit_category(step, plan, state)
        if explicit:
            return {"category": explicit, "confidence": 1.0, "source": "explicit_contract"}
        graph = self._load_graph()
        text = self._text([capability, step.get("step_type"), step.get("objective"), step.get("required_capability"), step.get("execution_strategy")])
        best = {"category": "unknown", "confidence": 0.0, "source": "unmatched"}
        for category, rule in graph.items():
            if not isinstance(rule, dict):
                continue
            indicators = [str(x).casefold() for x in rule.get("indicators", []) if str(x).strip()]
            if indicators and any(ind in text for ind in indicators):
                score = min(0.95, 0.55 + 0.1 * sum(1 for ind in indicators if ind in text))
                if score > best["confidence"]:
                    best = {"category": str(category), "confidence": score, "source": "indicator_contract"}
        return best

    def _explicit_category(self, *items: Any) -> str:
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("semantic_category", "capability_semantic_category", "source_category"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            policy = item.get("capability_policy") or item.get("source_policy")
            if isinstance(policy, dict):
                value = policy.get("semantic_category") or policy.get("capability_semantic_category")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def _load_graph(self) -> dict[str, Any]:
        graph: dict[str, Any] = {}
        for path in (
            CONFIGS_DIR / "semantic_capability_taxonomy.json",
            RUNTIME_GENERATED / "system_topology" / "runtime_governance_graph.json",
            RUNTIME_GENERATED / "contracts" / "semantic_capability_taxonomy.json",
        ):
            data = self.loader.load_json(path)
            if not isinstance(data, dict):
                continue
            candidate = data.get("capability_semantic_graph") if isinstance(data.get("capability_semantic_graph"), dict) else data
            if isinstance(candidate, dict):
                for key, value in candidate.items():
                    if isinstance(value, dict):
                        graph[str(key)] = {**graph.get(str(key), {}), **value}
        return graph

    def _text(self, values: list[Any]) -> str:
        parts: list[str] = []
        def walk(value: Any) -> None:
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (int, float, bool)):
                parts.append(str(value))
            elif isinstance(value, dict):
                for k, v in value.items():
                    parts.append(str(k)); walk(v)
            elif isinstance(value, list):
                for item in value: walk(item)
        for value in values:
            walk(value)
        return " ".join(parts).casefold()

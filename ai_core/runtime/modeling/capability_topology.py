from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED, RUNTIME_CONFIGS


class RuntimeModelTopology:
    """Loads runtime model topology from source config and generated overlays."""

    def __init__(self) -> None:
        self.loader = ConfigLoader()

    def load(self) -> dict[str, Any]:
        base = self._load_json(CONFIGS_DIR / "model_routing_topology.json")
        runtime_overlay = self._load_json(RUNTIME_GENERATED / "modeling" / "routing_topology.json")
        governance_overlay = self._load_json(RUNTIME_GENERATED / "system_topology" / "runtime_governance_graph.json")
        config_overlay = self._load_yaml(RUNTIME_CONFIGS / "models" / "model_routing_topology.yaml")
        return self._merge(self._merge(self._merge(base, config_overlay), runtime_overlay), governance_overlay)

    def ensure_defaults(self) -> None:
        path = CONFIGS_DIR / "model_routing_topology.json"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.default_topology(), ensure_ascii=False, indent=2), encoding="utf-8")

    def default_topology(self) -> dict[str, Any]:
        return {
            "version": "2.8.15",
            "description": "Generic cognitive model routing topology. No business-domain rules are stored here.",
            "medium_prompt_chars": 4000,
            "large_prompt_chars": 10000,
            "medium_schema_chars": 4000,
            "large_schema_chars": 10000,
            "high_weight_capabilities": [
                "semantic_grounding",
                "workflow_planning",
                "evidence_verification",
                "stable_synthesis",
                "tool_selection",
                "structured_output"
            ],
            "critical_weight_capabilities": [
                "code_generation",
                "tool_generation",
                "schema_design",
                "artifact_generation",
                "irreversible_action_planning"
            ],
            "nodes": {
                "input_parsing": {"base_complexity": "low", "route_name": "input_parsing"},
                "intent_recognition": {"base_complexity": "low", "route_name": "intent_simple", "escalate_route_name": "intent_complex"},
                "workflow_planning": {"base_complexity": "medium", "route_name": "workflow_basic", "escalate_route_name": "workflow_complex"},
                "execution": {"base_complexity": "medium", "route_name": "tool_selection", "escalate_route_name": "semantic_grounding"},
                "output": {"base_complexity": "medium", "route_name": "stable_synthesis", "escalate_route_name": "stable_synthesis_strong"}
            },
            "complexity_routes": {
                "low": "local_light",
                "medium": "local_capable",
                "high": "strong_reasoning",
                "critical": "strong_reasoning"
            },
            "feedback_escalation": {
                "failure_threshold": 2,
                "dissatisfaction_threshold": 1,
                "min_quality_score": 0.72,
                "always_escalate_levels": ["critical"]
            }
        }

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        try:
            data = self.loader.load_yaml(path)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _merge(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        result = dict(left or {})
        for key, value in (right or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._merge(result[key], value)
            elif isinstance(value, list) and isinstance(result.get(key), list):
                result[key] = [*result[key], *value]
            else:
                result[key] = value
        return result

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED


@dataclass
class BrainModelRoute:
    """Normalized model route used across all brain/model call sites.

    Older and diagnostic paths may construct a route with only provider/model
    for observability events.  Keep this object backward-compatible while the
    router still records full brain/task/complexity decisions for real calls.
    """

    brain: str = "runtime_brain"
    task_type: str = "default"
    complexity: str = "default"
    provider: str = ""
    model: str = ""
    model_alias: str = ""
    source: str = "brain_model_policy"
    options: dict[str, Any] = field(default_factory=dict)
    fallback: list[dict[str, Any]] = field(default_factory=list)
    decision_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["brain"] = str(payload.get("brain") or "runtime_brain")
        payload["task_type"] = str(payload.get("task_type") or "default")
        payload["complexity"] = str(payload.get("complexity") or "default")
        payload["provider"] = str(payload.get("provider") or "")
        payload["model"] = str(payload.get("model") or "")
        return payload


class BrainModelRouter:
    """Policy-based LLM selection for separated brains.

    This module is framework code, so it lives under ai_core rather than the
    runtime generated area.  It never hard-codes a concrete model in business
    code.  Each brain asks for a role/task/complexity route, and policy decides
    which LiteLLM provider/model should be used. Runtime only stores decision
    history for observability.
    """

    def __init__(self, *, policy_path: Path | None = None, decision_root: Path | None = None) -> None:
        self.policy_path = policy_path or (CONFIGS_DIR / "brain_model_policy.yaml")
        self.decision_root = decision_root or (RUNTIME_GENERATED / "model_decisions")
        self.decision_root.mkdir(parents=True, exist_ok=True)

    def select(self, *, brain: str, task_type: str = "default", complexity: str = "default", context: dict[str, Any] | None = None) -> BrainModelRoute:
        policy = self._load_policy()
        defaults = policy.get("defaults") if isinstance(policy.get("defaults"), dict) else {}
        brains = policy.get("brains") if isinstance(policy.get("brains"), dict) else {}
        brain_policy = brains.get(brain) if isinstance(brains.get(brain), dict) else {}
        route_def = self._resolve_route_definition(brain_policy, task_type=task_type, complexity=complexity)
        if not route_def:
            route_def = defaults.get("route") if isinstance(defaults.get("route"), dict) else {}
        provider = str(route_def.get("provider") or defaults.get("provider") or "").strip()
        model = str(route_def.get("model") or defaults.get("model") or "").strip()
        alias = str(route_def.get("model_alias") or route_def.get("alias") or "").strip()
        route = BrainModelRoute(
            brain=str(brain or "generic_brain"),
            task_type=str(task_type or "default"),
            complexity=str(complexity or "default"),
            provider=provider,
            model=model,
            model_alias=alias,
            options=route_def.get("options") if isinstance(route_def.get("options"), dict) else {},
            fallback=route_def.get("fallback") if isinstance(route_def.get("fallback"), list) else [],
            decision_reason=self._reason(brain_policy, task_type=task_type, complexity=complexity, route_def=route_def),
        )
        self.record_decision(route=route, context=context or {})
        return route

    def record_decision(self, *, route: BrainModelRoute, context: dict[str, Any] | None = None) -> None:
        event = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "route": route.to_dict(),
            "context": context or {},
        }
        path = self.decision_root / "brain_model_decisions.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def _load_policy(self) -> dict[str, Any]:
        if not self.policy_path.exists():
            return {}
        try:
            data = yaml.safe_load(self.policy_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _resolve_route_definition(self, brain_policy: dict[str, Any], *, task_type: str, complexity: str) -> dict[str, Any]:
        task_routes = brain_policy.get("tasks") if isinstance(brain_policy.get("tasks"), dict) else {}
        complexity_routes = brain_policy.get("complexities") if isinstance(brain_policy.get("complexities"), dict) else {}
        if task_type in task_routes and isinstance(task_routes[task_type], dict):
            task_def = task_routes[task_type]
            nested = task_def.get("complexities") if isinstance(task_def.get("complexities"), dict) else {}
            if complexity in nested and isinstance(nested[complexity], dict):
                return nested[complexity]
            return task_def
        if complexity in complexity_routes and isinstance(complexity_routes[complexity], dict):
            return complexity_routes[complexity]
        default = brain_policy.get("default") if isinstance(brain_policy.get("default"), dict) else {}
        return default

    def _reason(self, brain_policy: dict[str, Any], *, task_type: str, complexity: str, route_def: dict[str, Any]) -> str:
        if task_type and isinstance((brain_policy.get("tasks") if isinstance(brain_policy, dict) else {}), dict) and task_type in brain_policy.get("tasks", {}):
            return "matched_task_type_policy"
        if complexity and isinstance((brain_policy.get("complexities") if isinstance(brain_policy, dict) else {}), dict) and complexity in brain_policy.get("complexities", {}):
            return "matched_complexity_policy"
        if route_def:
            return "matched_brain_default_policy"
        return "matched_global_default_policy"

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED
from ai_core.secrets.secret_store import SecretStore
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore


@dataclass
class BrainModelRoute:
    brain: str
    task_type: str
    complexity: str
    provider: str
    model: str
    model_alias: str = ""
    source: str = "brain_model_policy"
    options: dict[str, Any] = field(default_factory=dict)
    fallback: list[dict[str, Any]] = field(default_factory=list)
    decision_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        route = self._apply_runtime_model_selection(route)
        self.record_decision(route=route, context=context or {})
        return route



    def _apply_runtime_model_selection(self, route: BrainModelRoute) -> BrainModelRoute:
        """Constrain brain policy routes by the user-facing runtime model mode.

        The policy file may describe high/critical API escalation routes, but the
        runtime settings page is the execution authority for whether API routes
        are allowed.  In local_only mode no brain may call an API provider.  If a
        policy route is disallowed, this method chooses the first allowed
        fallback; when none exists it falls back to the selected runtime model.
        The logic is provider-family based and remains independent of task or
        business vocabulary.
        """
        try:
            selection = UserModelSelectionStore().snapshot()
        except Exception:
            return route

        allowed_fallbacks = [item for item in (route.fallback or []) if self._route_item_allowed(item, selection)]
        if self._provider_model_allowed(route.provider, route.model, selection) and self._route_secret_available(route.provider):
            if len(allowed_fallbacks) != len(route.fallback or []):
                route = BrainModelRoute(
                    brain=route.brain,
                    task_type=route.task_type,
                    complexity=route.complexity,
                    provider=route.provider,
                    model=route.model,
                    model_alias=route.model_alias,
                    source=route.source,
                    options=dict(route.options or {}),
                    fallback=allowed_fallbacks,
                    decision_reason=route.decision_reason + "; runtime_model_mode_filtered_fallbacks",
                )
            return route

        replacement = allowed_fallbacks[0] if allowed_fallbacks else self._runtime_default_route(selection)
        provider = str(replacement.get("provider") or "").strip()
        model = str(replacement.get("model") or "").strip()
        options = replacement.get("options") if isinstance(replacement.get("options"), dict) else dict(route.options or {})
        remaining_fallbacks = allowed_fallbacks[1:] if allowed_fallbacks else []
        return BrainModelRoute(
            brain=route.brain,
            task_type=route.task_type,
            complexity=route.complexity,
            provider=provider,
            model=model,
            model_alias=str(replacement.get("model_alias") or replacement.get("alias") or route.model_alias or ""),
            source=route.source,
            options=options,
            fallback=remaining_fallbacks,
            decision_reason=route.decision_reason + "; runtime_model_mode_replaced_disallowed_route",
        )

    def _route_item_allowed(self, item: dict[str, Any], selection: Any) -> bool:
        if not isinstance(item, dict):
            return False
        provider = str(item.get("provider") or "").strip()
        model = str(item.get("model") or "").strip()
        return self._provider_model_allowed(provider, model, selection) and self._route_secret_available(provider)

    def _provider_model_allowed(self, provider: str, model: str, selection: Any) -> bool:
        provider = str(provider or "").strip()
        model = str(model or "").strip()
        if not provider and "/" in model:
            provider = model.split("/", 1)[0]
        is_local = self._provider_is_local(provider, model)
        if getattr(selection, "local_only", False):
            return is_local
        if getattr(selection, "api_only", False):
            return not is_local
        return True

    def _provider_is_local(self, provider: str, model: str = "") -> bool:
        text = str(provider or "").strip().casefold()
        model_text = str(model or "").strip().casefold()
        if text.startswith(("ollama", "vllm", "lmstudio", "huggingface_local")):
            return True
        if text in {"openai", "claude", "anthropic", "azure", "gemini"}:
            return False
        if ":" in model_text or model_text.startswith(("qwen", "llama", "mistral", "deepseek", "gemma", "phi", "codellama")):
            return True
        return False

    def _route_secret_available(self, provider: str) -> bool:
        provider = str(provider or "").strip().casefold()
        secret_key = ""
        if provider == "openai":
            secret_key = "OPENAI_API_KEY"
        elif provider in {"claude", "anthropic"}:
            secret_key = "ANTHROPIC_API_KEY"
        if not secret_key:
            return True
        try:
            return bool(os.getenv(secret_key) or SecretStore().get(secret_key))
        except Exception:
            return bool(os.getenv(secret_key))

    def _runtime_default_route(self, selection: Any) -> dict[str, Any]:
        if getattr(selection, "api_only", False):
            return {"provider": getattr(selection, "initial_provider", "openai"), "model": getattr(selection, "selected_api_model_id", "") or getattr(selection, "initial_model_id", "")}
        return {"provider": getattr(selection, "initial_provider", "ollama") or "ollama", "model": getattr(selection, "selected_local_model_id", "") or getattr(selection, "initial_model_id", "") or "qwen3.5:2b"}

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

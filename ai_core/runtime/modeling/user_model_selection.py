from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import CONFIGS_DIR, RUNTIME_CONFIGS, RUNTIME_GENERATED
from ai_core.secrets.secret_store import SecretStore

_LOCAL_PROVIDER_IDS = {
    "vllm", "vllm_coder", "ollama", "ollama_coder_qwen25", "ollama_coder_deepseek",
    "ollama_embedding", "lmstudio", "lmstudio_coder", "huggingface_local",
}
_API_PROVIDER_IDS = {"openai", "claude"}


@dataclass(frozen=True)
class UserModelSelectionSnapshot:
    mode: str = "local_only"  # local_only | api_only | hybrid
    initial_model_id: str = "qwen3.5:2b-instruct"
    initial_provider: str = "ollama"
    selected_local_model_id: str = "qwen3.5:2b-instruct"
    selected_api_model_id: str = "gpt-4o-mini"
    selected_provider: str = "auto"
    custom_endpoint: str = ""
    allow_escalation: bool = True
    ask_for_missing_keys_at_start: bool = True
    updated_at: str = ""
    source: str = "default"

    @property
    def local_enabled(self) -> bool:
        return self.mode in {"local_only", "hybrid"}

    @property
    def api_enabled(self) -> bool:
        return self.mode in {"api_only", "hybrid"}

    @property
    def local_only(self) -> bool:
        return self.mode == "local_only"

    @property
    def api_only(self) -> bool:
        return self.mode == "api_only"


class UserModelSelectionStore:
    """User-facing runtime model mode and initial model selection.

    This is a domain-neutral UI preference layer.  It decides which deployment
    families are allowed and which model should be tried first.  Stage policy
    still controls later specialist model selection and escalation.
    """

    VALID_MODES = {"local_only", "api_only", "hybrid"}

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.path = RUNTIME_CONFIGS / "model_selection.json"
        self.stage_policy_path = RUNTIME_GENERATED / "system_topology" / "model_stage_policy.json"
        self.stage_seed_path = CONFIGS_DIR / "model_stage_policy.seed.json"
        self.provider_config_path = RUNTIME_CONFIGS / "models" / "providers.yaml"

    def snapshot(self) -> UserModelSelectionSnapshot:
        data = self._read()
        mode = self._normalize_mode(data.get("mode") or os.getenv("AI_CORE_MODEL_MODE") or "local_only")
        local_default = self._default_local_model()
        api_default = self._default_api_model()
        local_model = str(data.get("selected_local_model_id") or local_default).strip() or local_default
        api_model = str(data.get("selected_api_model_id") or api_default).strip() or api_default
        initial = str(data.get("initial_model_id") or "").strip()
        if mode == "local_only":
            initial = local_model or local_default
        elif mode == "api_only":
            initial = api_model or api_default
        elif not initial:
            initial = data.get("initial_model_id") or local_model or api_model
        provider = self.provider_for_model(initial) or ("openai" if mode == "api_only" else "ollama")
        return UserModelSelectionSnapshot(
            mode=mode,
            initial_model_id=initial,
            initial_provider=provider,
            selected_local_model_id=local_model,
            selected_api_model_id=api_model,
            selected_provider=str(data.get("selected_provider") or "auto"),
            custom_endpoint=str(data.get("custom_endpoint") or ""),
            allow_escalation=bool(data.get("allow_escalation", True)),
            ask_for_missing_keys_at_start=bool(data.get("ask_for_missing_keys_at_start", True)),
            updated_at=str(data.get("updated_at") or ""),
            source=str(data.get("source") or "runtime_config"),
        )

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.snapshot()
        mode = self._normalize_mode(payload.get("mode") or current.mode)
        local_model = str(payload.get("selected_local_model_id") or current.selected_local_model_id or self._default_local_model()).strip()
        api_model = str(payload.get("selected_api_model_id") or current.selected_api_model_id or self._default_api_model()).strip()
        initial = str(payload.get("initial_model_id") or "").strip()
        if mode == "local_only":
            initial = local_model
        elif mode == "api_only":
            initial = api_model
        elif not initial:
            initial = local_model or api_model
        data = {
            "mode": mode,
            "initial_model_id": initial,
            "initial_provider": self.provider_for_model(initial),
            "selected_local_model_id": local_model,
            "selected_api_model_id": api_model,
            "selected_provider": str(payload.get("selected_provider") or current.selected_provider or "auto"),
            "custom_endpoint": str(payload.get("custom_endpoint") or current.custom_endpoint or ""),
            "allow_escalation": bool(payload.get("allow_escalation", current.allow_escalation)),
            "ask_for_missing_keys_at_start": bool(payload.get("ask_for_missing_keys_at_start", current.ask_for_missing_keys_at_start)),
            "source": "agent_studio_ui",
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.state()

    def state(self) -> dict[str, Any]:
        snap = self.snapshot()
        local_models = self.available_models("local")
        api_models = self.available_models("api")
        selected = snap.initial_model_id
        required_secret = self.required_secret_for_model(selected)
        secret_available = bool(required_secret and SecretStore().get(required_secret)) if required_secret else True
        return {
            "selection": snap.__dict__,
            "available_models": {
                "local": local_models,
                "api": api_models,
                "all": local_models + api_models,
            },
            "required_secret": required_secret,
            "required_secret_available": secret_available,
            "secret_prompt_required": bool(required_secret and not secret_available and snap.ask_for_missing_keys_at_start),
            "policy_path": str(self.path),
        }

    def available_models(self, family: str | None = None) -> list[dict[str, Any]]:
        policy = self._load_policy()
        catalog = policy.get("model_catalog") if isinstance(policy.get("model_catalog"), dict) else {}
        result: list[dict[str, Any]] = []
        for model_id, meta in catalog.items():
            if not isinstance(meta, dict):
                continue
            item_family = self.family_for_model_meta(meta)
            if family and item_family != family:
                continue
            item = {
                "model_id": model_id,
                "label": meta.get("label") or model_id,
                "family": item_family,
                "provider": meta.get("provider_template") or self.provider_for_model(model_id, meta),
                "tier": meta.get("tier"),
                "cost_class": meta.get("cost_class"),
                "capabilities": meta.get("capabilities", []),
                "requires_secret": self.required_secret_for_model(model_id, meta),
            }
            result.append(item)
        if not result and family == "local":
            result = [{"model_id": "qwen3.5:2b-instruct", "label": "Qwen3.5 2B Instruct", "family": "local", "provider": "ollama", "cost_class": "local", "requires_secret": None}]
        if not result and family == "api":
            result = [{"model_id": "gpt-4o-mini", "label": "gpt-4o-mini", "family": "api", "provider": "openai", "cost_class": "metered", "requires_secret": "OPENAI_API_KEY"}]
        return sorted(result, key=lambda x: (0 if x.get("model_id") in {"qwen3.5:2b-instruct", "gpt-4o-mini"} else 1, str(x.get("model_id"))))

    def route_allowed(self, provider_name: str, provider: dict[str, Any] | None = None) -> bool:
        snap = self.snapshot()
        is_local = self.provider_is_local(provider_name, provider or {})
        if snap.local_only:
            return is_local
        if snap.api_only:
            return not is_local
        return True

    def provider_is_local(self, provider_name: str, provider: dict[str, Any] | None = None) -> bool:
        provider = provider or {}
        base_url = str(provider.get("base_url") or "").lower()
        protocol = str(provider.get("protocol") or "").lower()
        role = str(provider.get("role") or "").lower()
        tags = {str(x).lower() for x in provider.get("model_tags", []) or []}
        if role.startswith("external"):
            return False
        return provider_name in _LOCAL_PROVIDER_IDS or protocol.startswith("ollama") or "local" in tags or "127.0.0.1" in base_url or "localhost" in base_url

    def family_for_model(self, model_id: str) -> str:
        meta = self._model_meta(model_id)
        return self.family_for_model_meta(meta) if meta else ("local" if model_id.startswith(("qwen", "llama", "deepseek")) else "api")

    def family_for_model_meta(self, meta: dict[str, Any]) -> str:
        deployment = str(meta.get("deployment") or "").lower()
        cost_class = str(meta.get("cost_class") or "").lower()
        provider = str(meta.get("provider_template") or "").lower()
        if deployment.startswith("local") or cost_class in {"local", "free"} or provider in _LOCAL_PROVIDER_IDS:
            return "local"
        return "api"

    def provider_for_model(self, model_id: str, meta: dict[str, Any] | None = None) -> str:
        meta = meta or self._model_meta(model_id) or {}
        family = self.family_for_model_meta(meta) if meta else self.family_for_model(model_id)
        if family == "local":
            provider_models = meta.get("provider_models") if isinstance(meta.get("provider_models"), dict) else {}
            for provider_id in self._local_provider_order():
                if not provider_models or provider_id in provider_models:
                    return provider_id
            provider = str(meta.get("provider_template") or "").strip()
            return provider or "vllm"
        provider = str(meta.get("provider_template") or "").strip()
        return provider or "openai"

    def provider_model_for(self, provider_name: str, model_id: str, meta: dict[str, Any] | None = None) -> str:
        meta = meta or self._model_meta(model_id) or {}
        provider_models = meta.get("provider_models") if isinstance(meta.get("provider_models"), dict) else {}
        mapped = str(provider_models.get(provider_name) or "").strip()
        if mapped:
            return mapped
        provider_model = str(meta.get("provider_model") or "").strip()
        return provider_model or model_id

    def required_secret_for_model(self, model_id: str, meta: dict[str, Any] | None = None) -> str | None:
        meta = meta or self._model_meta(model_id) or {}
        explicit = str(meta.get("required_secret") or meta.get("secret_key") or "").strip()
        if explicit:
            return explicit
        provider = self.provider_for_model(model_id, meta)
        if provider == "openai":
            return "OPENAI_API_KEY"
        if provider == "claude":
            return "ANTHROPIC_API_KEY"
        return None

    def initial_adapter_overrides(self, adapter: dict[str, Any] | None = None) -> dict[str, Any]:
        adapter = dict(adapter or {})
        snap = self.snapshot()
        adapter["user_model_mode"] = snap.mode
        adapter["initial_model_id"] = snap.initial_model_id
        adapter["preferred_local_model"] = snap.selected_local_model_id
        adapter["preferred_api_model"] = snap.selected_api_model_id
        return adapter

    def reorder_candidates(self, candidates: list[str], *, escalated: bool = False) -> list[str]:
        snap = self.snapshot()
        if not snap.allow_escalation or not escalated:
            preferred = snap.initial_model_id
            if preferred in candidates:
                return [preferred] + [c for c in candidates if c != preferred]
        # When escalated, keep stage upper-substitute order but remove models
        # disallowed by current mode.
        return candidates

    def _read(self) -> dict[str, Any]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
        return {}

    def _load_policy(self) -> dict[str, Any]:
        for path in [self.stage_policy_path, self.stage_seed_path]:
            try:
                if path.exists():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data:
                        return data
            except Exception:
                pass
        return {}

    def _model_meta(self, model_id: str) -> dict[str, Any] | None:
        catalog = self._load_policy().get("model_catalog")
        if isinstance(catalog, dict) and isinstance(catalog.get(model_id), dict):
            return catalog[model_id]
        return None

    def _local_provider_order(self) -> list[str]:
        policy = self._load_policy()
        try:
            order = policy.get("global_policy", {}).get("runtime_execution_policy", {}).get("local_provider_order")
            if isinstance(order, list) and order:
                return [str(x) for x in order if str(x)]
        except Exception:
            pass
        return ["vllm", "ollama"]

    def _default_local_model(self) -> str:
        ids = [m["model_id"] for m in self.available_models("local") if m.get("model_id")]
        for preferred in ["qwen3.5:2b-instruct", "qwen3.5:4b-instruct", "qwen3:4b", "qwen3:8b", "qwen2.5:7b", "qwen3:14b"]:
            if preferred in ids:
                return preferred
        return ids[0] if ids else "qwen3.5:2b-instruct"

    def _default_api_model(self) -> str:
        ids = [m["model_id"] for m in self.available_models("api") if m.get("model_id")]
        for preferred in ["gpt-4o-mini", "gpt-4.1", "gpt-5.x"]:
            if preferred in ids:
                return preferred
        return ids[0] if ids else "gpt-4o-mini"

    def _normalize_mode(self, mode: Any) -> str:
        text = str(mode or "").strip().lower().replace("-", "_")
        aliases = {"local": "local_only", "api": "api_only", "mixed": "hybrid", "mix": "hybrid"}
        text = aliases.get(text, text)
        return text if text in self.VALID_MODES else "api_only"

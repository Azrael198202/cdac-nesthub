from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore


_LOCAL_PROVIDER_IDS = {
    "vllm",
    "vllm_coder",
    "ollama",
    "ollama_coder_qwen25",
    "ollama_coder_deepseek",
    "ollama_embedding",
    "lmstudio",
    "lmstudio_coder",
    "huggingface_local",
}

_TRUE_VALUES = {"1", "true", "yes", "on", "local", "local_first", "local-first"}
_FALSE_VALUES = {"0", "false", "no", "off", "api_only", "api-only", "api"}


@dataclass(frozen=True)
class RuntimeExecutionPolicySnapshot:
    """Single source of truth for provider/runtime execution switches."""

    local_enabled: bool = False
    default_mode: str = "api_only"
    api_enabled: bool = True
    api_provider_order: list[str] = field(default_factory=lambda: ["openai", "claude"])
    local_provider_order: list[str] = field(default_factory=lambda: ["ollama"])
    local_code_provider_order: list[str] = field(default_factory=lambda: ["ollama_coder_qwen25", "ollama_coder_deepseek"])
    api_only_when_local_disabled: bool = True
    credential_recovery_enabled: bool = True

    def provider_is_local(self, provider_name: str, provider: dict[str, Any] | None = None) -> bool:
        provider = provider if isinstance(provider, dict) else {}
        base_url = str(provider.get("base_url") or "").lower()
        protocol = str(provider.get("protocol") or "").lower()
        tags = {str(x).lower() for x in provider.get("model_tags", []) or []}
        role = str(provider.get("role") or "").lower()
        if role.startswith("external"):
            return False
        return (
            provider_name in _LOCAL_PROVIDER_IDS
            or "local" in tags
            or protocol.startswith("ollama")
            or "127.0.0.1" in base_url
            or "localhost" in base_url
        )

    def filter_route(self, route: list[str], providers: dict[str, Any]) -> list[str]:
        filtered = []
        for provider_name in route:
            provider = providers.get(provider_name, {}) if isinstance(providers, dict) else {}
            is_local = self.provider_is_local(provider_name, provider)
            if self.default_mode == "local_only" and not is_local:
                continue
            if self.default_mode == "api_only" and is_local:
                continue
            if not self.local_enabled and self.api_only_when_local_disabled and is_local:
                continue
            filtered.append(provider_name)
        if self.default_mode == "local_only":
            for provider_name in self.local_provider_order:
                if isinstance(providers, dict) and provider_name in providers and provider_name not in filtered:
                    filtered.append(provider_name)
        elif self.default_mode == "api_only":
            for provider_name in self.api_provider_order:
                if isinstance(providers, dict) and provider_name in providers and provider_name not in filtered:
                    filtered.append(provider_name)
        else:
            for provider_name in list(self.local_provider_order) + list(self.api_provider_order):
                if isinstance(providers, dict) and provider_name in providers and provider_name not in filtered:
                    filtered.append(provider_name)
        return filtered

    def to_provider_policy(self) -> dict[str, Any]:
        return {
            "runtime_execution_policy": {
                "default_mode": self.default_mode,
                "local_enabled": self.local_enabled,
                "api_enabled": self.api_enabled,
                "api_only_when_local_disabled": self.api_only_when_local_disabled,
                "api_provider_order": self.api_provider_order,
                "local_provider_order": self.local_provider_order,
                "local_code_provider_order": self.local_code_provider_order,
                "credential_recovery_enabled": self.credential_recovery_enabled,
                "source_of_truth": "runtime_execution_policy",
            },
            # Backward-compatible mirror for legacy components. Do not use as
            # an authority in new code.
            "local_models_enabled": self.local_enabled,
            "api_only_when_local_disabled": self.api_only_when_local_disabled,
            "api_provider_order": self.api_provider_order,
            "local_provider_order": self.local_provider_order,
        }


class RuntimeExecutionPolicy:
    """Reads the runtime execution switch from one canonical location.

    Authority order:
    1. environment variable AI_CORE_LOCAL_MODELS_ENABLED
    2. global_policy.runtime_execution_policy.local_enabled
    3. legacy mirrors, only for backward compatibility
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.runtime_policy_path = RUNTIME_GENERATED / "system_topology" / "model_stage_policy.json"
        self.seed_policy_path = CONFIGS_DIR / "model_stage_policy.seed.json"
        self.user_selection = UserModelSelectionStore()

    def snapshot(self, policy: dict[str, Any] | None = None, provider_config: dict[str, Any] | None = None) -> RuntimeExecutionPolicySnapshot:
        policy = policy if isinstance(policy, dict) else self._load_policy()
        provider_config = provider_config if isinstance(provider_config, dict) else {}
        global_policy = policy.get("global_policy") if isinstance(policy.get("global_policy"), dict) else {}
        canonical = global_policy.get("runtime_execution_policy") if isinstance(global_policy.get("runtime_execution_policy"), dict) else {}
        legacy_switch = global_policy.get("runtime_switch") if isinstance(global_policy.get("runtime_switch"), dict) else {}
        legacy_local = global_policy.get("local_model_policy") if isinstance(global_policy.get("local_model_policy"), dict) else {}
        provider_policy = provider_config.get("policy") if isinstance(provider_config.get("policy"), dict) else {}
        provider_canonical = provider_policy.get("runtime_execution_policy") if isinstance(provider_policy.get("runtime_execution_policy"), dict) else {}

        selection = self.user_selection.snapshot()
        local_enabled = selection.local_enabled
        api_enabled = selection.api_enabled
        env_value = os.getenv("AI_CORE_LOCAL_MODELS_ENABLED")
        if env_value is not None:
            local_enabled = self._parse_bool(env_value, default=local_enabled)
            if local_enabled and selection.mode == "api_only":
                api_enabled = True

        default_mode = str(selection.mode or canonical.get("default_mode") or provider_canonical.get("default_mode") or ("hybrid" if local_enabled and api_enabled else ("local_only" if local_enabled else "api_only")))
        api_order = self._string_list(
            canonical.get("api_provider_order")
            or provider_canonical.get("api_provider_order")
            or legacy_local.get("api_provider_order")
            or provider_policy.get("api_provider_order")
            or ["openai", "claude"]
        )
        local_order = self._string_list(
            canonical.get("local_provider_order")
            or provider_canonical.get("local_provider_order")
            or legacy_local.get("default_provider_order")
            or provider_policy.get("local_provider_order")
            or ["ollama"]
        )
        local_code_order = self._string_list(
            canonical.get("local_code_provider_order")
            or provider_canonical.get("local_code_provider_order")
            or legacy_local.get("code_provider_order")
            or ["ollama_coder_qwen25", "ollama_coder_deepseek"]
        )
        api_only = self._coalesce_bool(
            canonical.get("api_only_when_local_disabled"),
            provider_canonical.get("api_only_when_local_disabled"),
            legacy_local.get("api_only_when_disabled"),
            provider_policy.get("api_only_when_local_disabled"),
            default=True,
        )
        credential_recovery = self._coalesce_bool(
            canonical.get("credential_recovery_enabled"),
            provider_canonical.get("credential_recovery_enabled"),
            default=True,
        )
        return RuntimeExecutionPolicySnapshot(
            local_enabled=bool(local_enabled),
            default_mode=default_mode,
            api_enabled=bool(api_enabled),
            api_provider_order=api_order,
            local_provider_order=local_order,
            local_code_provider_order=local_code_order,
            api_only_when_local_disabled=bool(api_only),
            credential_recovery_enabled=bool(credential_recovery),
        )

    def _load_policy(self) -> dict[str, Any]:
        data = self.loader.load_json(self.runtime_policy_path)
        if isinstance(data, dict) and data:
            return data
        data = self.loader.load_json(self.seed_policy_path)
        return data if isinstance(data, dict) else {}

    def _coalesce_bool(self, *values: Any, default: bool) -> bool:
        for value in values:
            if value is None:
                continue
            return self._parse_bool(value, default=default)
        return default

    def _parse_bool(self, value: Any, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE_VALUES:
            return True
        if text in _FALSE_VALUES:
            return False
        return default

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            result = [str(x).strip() for x in value if str(x).strip()]
            return result
        text = str(value or "").strip()
        return [text] if text else []

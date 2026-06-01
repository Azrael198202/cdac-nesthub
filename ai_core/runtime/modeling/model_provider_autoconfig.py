from __future__ import annotations

from copy import deepcopy
import os
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS


class ModelProviderAutoConfigurator:
    """Creates and repairs generic model-provider runtime configuration.

    This class is intentionally domain-neutral. It only prepares provider
    connection templates and model aliases. It does not inspect user tasks or
    encode task-domain keywords.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.path = RUNTIME_CONFIGS / "models" / "providers.yaml"

    def ensure(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        current = self.loader.load_yaml(self.path) if self.path.exists() else {}
        if not isinstance(current, dict):
            current = {}
        desired = self.default_config()
        merged = self.merge(current, desired)
        self.loader.save_yaml(self.path, merged)
        return merged

    def default_config(self) -> dict[str, Any]:
        return {
            "default_route": ["ollama", "openai", "claude"],
            "routes": {
                "input_parsing": ["ollama", "openai", "claude"],
                "intent_recognition": ["ollama", "openai", "claude"],
                "workflow_planning": ["ollama", "openai", "claude"],
                "reasoning": ["ollama", "openai", "claude"],
                "stable_synthesis": ["ollama", "openai", "claude"],
                "code_generation": ["ollama_coder_qwen25", "openai"],
                "fallback": ["ollama", "openai", "claude"],
            },
            "providers": {
                "openai": {
                    "enabled": True,
                    "type": "universal_model",
                    "protocol": "openai_compatible",
                    "base_url": "https://api.openai.com",
                    "endpoint": "/v1/chat/completions",
                    "model": "gpt-4o-mini",
                    "auth_type": "bearer_env",
                    "auth_env": "OPENAI_API_KEY",
                    "timeout_seconds": 60,
                    "response_format_json": True,
                    "model_tags": ["api", "reasoning", "json_generation"],
                    "capabilities": ["reasoning", "json_generation"],
                },
                "claude": {
                    "enabled": False,
                    "type": "universal_model",
                    "protocol": "openai_compatible",
                    "base_url": "https://api.anthropic.com",
                    "endpoint": "/v1/messages",
                    "model": "claude-sonnet",
                    "auth_type": "bearer_env",
                    "auth_env": "ANTHROPIC_API_KEY",
                    "timeout_seconds": 60,
                    "response_format_json": True,
                    "model_tags": ["api", "reasoning", "json_generation"],
                    "capabilities": ["reasoning", "json_generation"],
                },
                "vllm": {
                    "enabled": False,
                    "type": "universal_model",
                    "protocol": "openai_compatible",
                    "base_url": "http://127.0.0.1:8001",
                    "endpoint": "/v1/chat/completions",
                    "model": "Qwen/Qwen3.5-2B-Instruct",
                    "logical_model_id": "qwen3.5:2b-instruct",
                    "auto_start": True,
                    "auto_install": False,
                    "ready_timeout_seconds": 120,
                    "ready_poll_interval_seconds": 2,
                    "start_command": "python -m vllm.entrypoints.openai.api_server --host 127.0.0.1 --port 8001 --model Qwen/Qwen3.5-2B-Instruct --served-model-name Qwen/Qwen3.5-2B-Instruct",
                    "timeout_seconds": 90,
                    "max_prompt_tokens": 12000,
                    "response_format_json": True,
                    "provider_models": {
                        "qwen3.5:2b-instruct": "Qwen/Qwen3.5-2B-Instruct",
                        "qwen3.5:4b-instruct": "Qwen/Qwen3.5-4B-Instruct",
                        "qwen3:8b": "Qwen/Qwen3-8B",
                        "qwen3:14b": "Qwen/Qwen3-14B",
                        "qwen3:32b": "Qwen/Qwen3-32B",
                    },
                    "model_tags": ["local", "reasoning", "json_generation"],
                    "capabilities": ["reasoning", "json_generation"],
                },
                "ollama": {
                    "enabled": True,
                    "type": "universal_model",
                    "protocol": "ollama_chat",
                    "base_url": "http://127.0.0.1:11434",
                    "binary": "ollama",
                    "auto_install": True,
                    "auto_start": True,
                    "auto_pull_missing_model": True,
                    "auto_import_gguf_missing_model": True,
                    "start_command": "{binary} serve",
                    "pull_command": "{binary} pull {model}",
                    "pull_timeout_seconds": 3600,
                    "gguf_download_timeout_seconds": 3600,
                    "gguf_create_timeout_seconds": 3600,
                    "install_timeout_seconds": 3600,
                    "ready_timeout_seconds": 60,
                    "ready_poll_interval_seconds": 1,
                    "install": {
                        "windows": ["winget install Ollama.Ollama --accept-source-agreements --accept-package-agreements --disable-interactivity"],
                        "macos": ["brew install ollama"],
                        "linux": ["curl -fsSL https://ollama.com/install.sh | sh"],
                    },
                    "executable_hints": {
                        "windows": ["%LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe", "%ProgramFiles%\\Ollama\\ollama.exe"]
                    },
                    "endpoint_strategy": "auto",
                    "chat_endpoint": "/api/chat",
                    "generate_endpoint": "/api/generate",
                    "model": "qwen3.5:2b-instruct",
                    "fallback_models": ["qwen3.5:2b-instruct", "qwen3.5:4b-instruct", "qwen3:4b", "qwen3:8b"],
                    "provider_models": {
                        "qwen3.5:2b-instruct": "qwen3.5:2b-instruct",
                        "qwen3.5:4b-instruct": "qwen3.5:4b-instruct",
                        "qwen3:8b": "qwen3:8b",
                        "qwen3:14b": "qwen3:14b",
                        "qwen3:32b": "qwen3:32b",
                    },
                    "timeout_seconds": 90,
                    "max_prompt_tokens": 12000,
                    "response_format_json": True,
                    "model_tags": ["local", "reasoning", "json_generation"],
                    "capabilities": ["reasoning", "json_generation"],
                },
                "vllm_coder": {
                    "enabled": False,
                    "type": "universal_model",
                    "protocol": "openai_compatible",
                    "base_url": "http://127.0.0.1:8002",
                    "endpoint": "/v1/chat/completions",
                    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
                    "auto_start": False,
                    "timeout_seconds": 90,
                    "response_format_json": True,
                    "model_tags": ["local", "code_generation", "json_generation"],
                    "capabilities": ["code_generation", "json_generation"],
                },
                "ollama_coder_qwen25": {
                    "enabled": True,
                    "type": "universal_model",
                    "protocol": "ollama_chat",
                    "base_url": "http://127.0.0.1:11434",
                    "binary": "ollama",
                    "auto_install": True,
                    "auto_start": True,
                    "auto_pull_missing_model": True,
                    "model": "qwen2.5-coder:7b",
                    "fallback_models": ["qwen2.5-coder:7b", "qwen2.5-coder:3b"],
                    "timeout_seconds": 90,
                    "model_tags": ["local", "code_generation", "json_generation"],
                    "capabilities": ["code_generation", "json_generation"],
                },
            },
            "policy": {
                "require_real_provider": True,
                "allow_placeholder_result": False,
                "local_provider_order": ["ollama", "vllm"],
                "api_provider_order": ["openai", "claude"],
            },
        }

    def _vllm_enabled_by_environment(self) -> bool:
        return str(os.getenv("AI_CORE_ENABLE_VLLM", "")).strip().lower() in {"1", "true", "yes", "on"}

    def _prefer_supported_local_runtime(self, config: dict[str, Any]) -> dict[str, Any]:
        """Keep Windows/default local execution on Ollama.

        vLLM is useful on Linux GPU environments, but it is not a safe default
        for Windows development.  It is only enabled when AI_CORE_ENABLE_VLLM=1.
        """
        enable_vllm = self._vllm_enabled_by_environment()
        providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
        for name in ("vllm", "vllm_coder"):
            if name in providers and not enable_vllm:
                providers[name]["enabled"] = False
                providers[name]["auto_start"] = False
                providers[name]["auto_install"] = False
                providers[name]["disabled_reason"] = "vllm_is_optional_enable_with_AI_CORE_ENABLE_VLLM"
        def normalize_route(route: Any) -> list[str]:
            if not isinstance(route, list):
                return []
            names = [str(x) for x in route if str(x)]
            if not enable_vllm:
                names = [x for x in names if not x.startswith("vllm")]
            order = ["ollama", "ollama_coder_qwen25", "ollama_coder_deepseek", "openai", "claude", "lmstudio", "lmstudio_coder"]
            ordered = [x for x in order if x in names]
            ordered.extend([x for x in names if x not in ordered])
            return ordered
        config["default_route"] = normalize_route(config.get("default_route")) or ["ollama", "openai"]
        routes = config.get("routes") if isinstance(config.get("routes"), dict) else {}
        for key, route in list(routes.items()):
            routes[key] = normalize_route(route) or ["ollama", "openai"]
        policy = config.get("policy") if isinstance(config.get("policy"), dict) else {}
        policy["local_provider_order"] = normalize_route(policy.get("local_provider_order")) or ["ollama"]
        rte = policy.get("runtime_execution_policy") if isinstance(policy.get("runtime_execution_policy"), dict) else {}
        if rte:
            rte["local_provider_order"] = normalize_route(rte.get("local_provider_order")) or ["ollama"]
            rte["local_code_provider_order"] = normalize_route(rte.get("local_code_provider_order")) or ["ollama_coder_qwen25"]
            policy["runtime_execution_policy"] = rte
        config["policy"] = policy
        return config

    def merge(self, current: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(current)
        for key in ["default_route"]:
            if not merged.get(key):
                merged[key] = deepcopy(desired.get(key))
        routes = dict(merged.get("routes") or {})
        for route_name, route in (desired.get("routes") or {}).items():
            routes.setdefault(route_name, deepcopy(route))
        merged["routes"] = routes
        providers = dict(merged.get("providers") or {})
        for provider_id, desired_provider in (desired.get("providers") or {}).items():
            existing = dict(providers.get(provider_id) or {})
            provider = deepcopy(desired_provider)
            provider.update(existing)
            # Preserve user endpoint overrides but force essential generic contract fields.
            for forced in ["type", "protocol"]:
                provider[forced] = desired_provider.get(forced)
            if provider_id in {"vllm", "ollama"}:
                for field in ["enabled", "auto_start", "auto_install", "provider_models", "model_tags", "capabilities"]:
                    provider[field] = existing.get(field, desired_provider.get(field))
            providers[provider_id] = provider
        merged["providers"] = providers
        policy = dict(merged.get("policy") or {})
        for key, value in (desired.get("policy") or {}).items():
            policy.setdefault(key, deepcopy(value))
        merged["policy"] = policy
        return self._prefer_supported_local_runtime(merged)

from __future__ import annotations

from copy import deepcopy
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
            "default_route": ["openai", "claude", "vllm", "ollama"],
            "routes": {
                "input_parsing": ["openai", "claude", "vllm", "ollama"],
                "intent_recognition": ["openai", "claude", "vllm", "ollama"],
                "workflow_planning": ["openai", "claude", "vllm", "ollama"],
                "reasoning": ["openai", "claude", "vllm", "ollama"],
                "stable_synthesis": ["openai", "claude", "vllm", "ollama"],
                "code_generation": ["vllm_coder", "ollama_coder_qwen25", "openai"],
                "fallback": ["openai", "claude", "vllm", "ollama"],
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
                    "enabled": True,
                    "type": "universal_model",
                    "protocol": "openai_compatible",
                    "base_url": "http://127.0.0.1:8001",
                    "endpoint": "/v1/chat/completions",
                    "model": "Qwen/Qwen3-8B",
                    "logical_model_id": "qwen3:8b",
                    "auto_start": True,
                    "auto_install": False,
                    "ready_timeout_seconds": 120,
                    "ready_poll_interval_seconds": 2,
                    "start_command": "python -m vllm.entrypoints.openai.api_server --host 127.0.0.1 --port 8001 --model Qwen/Qwen3-8B --served-model-name Qwen/Qwen3-8B",
                    "timeout_seconds": 90,
                    "max_prompt_tokens": 12000,
                    "response_format_json": True,
                    "provider_models": {
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
                    "start_command": "{binary} serve",
                    "pull_command": "{binary} pull {model}",
                    "pull_timeout_seconds": 3600,
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
                    "model": "qwen3:8b",
                    "fallback_models": ["qwen3:8b", "qwen3:4b", "qwen3:1.7b"],
                    "provider_models": {
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
                    "enabled": True,
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
                "local_provider_order": ["vllm", "ollama"],
                "api_provider_order": ["openai", "claude"],
            },
        }

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
        return merged

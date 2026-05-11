from __future__ import annotations

from typing import Any

from ai_core.llm.providers import LocalRuleProvider, OllamaProvider, OpenAIProvider, LLMResult
from ai_core.runtime.runtime_config import RuntimeConfig


class ModelRouter:
    def __init__(self) -> None:
        self.config = RuntimeConfig()

    async def complete(self, prompt: str, user_input: str, context: dict[str, Any]) -> LLMResult:
        routes = self.config.model_routes()
        providers_cfg = routes.get("providers", {})
        errors: list[str] = []
        for provider_name in routes.get("selection_order", ["local_rules", "ollama", "openai"]):
            cfg = providers_cfg.get(provider_name, {})
            if cfg.get("enabled") is False:
                continue
            provider = self._make_provider(provider_name, cfg)
            if provider is None:
                continue
            result = await provider.complete(prompt, user_input, context)
            if result.ok and result.content.strip():
                return result
            errors.append(f"{provider_name}: {result.error}")
        return LLMResult(False, "none", "", " | ".join(errors) or "No provider available")

    def _make_provider(self, name: str, cfg: dict[str, Any]):
        if name == "local_rules":
            return LocalRuleProvider()
        if name == "ollama":
            return OllamaProvider(cfg.get("base_url", "http://127.0.0.1:11434"), cfg.get("model", "qwen3:4b"))
        if name == "openai":
            return OpenAIProvider(cfg.get("model", "gpt-4o-mini"))
        return None

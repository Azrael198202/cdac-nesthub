from __future__ import annotations

from typing import Any, AsyncGenerator

from ai_core.llm.providers import HuggingFaceEndpointProvider, OllamaProvider, OpenAIProvider, LLMResult, BaseProvider
from ai_core.runtime.runtime_config import RuntimeConfig


class ModelRouter:
    """Config-driven model router.

    The router has no task/business knowledge. Runtime config selects providers.
    """

    def __init__(self) -> None:
        self.config = RuntimeConfig()

    async def complete(self, prompt: str, user_input: str, context: dict[str, Any]) -> LLMResult:
        provider, errors = self._first_available_provider()
        if provider is None:
            return LLMResult(False, "none", "", " | ".join(errors) or "No provider configured")
        result = await provider.complete(prompt, user_input, context)
        if result.ok and result.content.strip():
            return result
        # Try remaining providers if the first one failed.
        routes = self.config.model_routes()
        providers_cfg = routes.get("providers", {})
        order = routes.get("selection_order", ["ollama", "huggingface", "openai"])
        for provider_name in order:
            p = self._make_provider(provider_name, providers_cfg.get(provider_name, {}))
            if p is None or p.name == provider.name:
                continue
            r = await p.complete(prompt, user_input, context)
            if r.ok and r.content.strip():
                return r
            errors.append(f"{provider_name}: {r.error}")
        errors.append(f"{provider.name}: {result.error}")
        return LLMResult(False, "none", "", " | ".join(errors))

    async def stream_complete(self, prompt: str, user_input: str, context: dict[str, Any]) -> AsyncGenerator[tuple[str, str], None]:
        provider, errors = self._first_available_provider()
        if provider is None:
            raise RuntimeError(" | ".join(errors) or "No provider configured")
        try:
            async for chunk in provider.stream_complete(prompt, user_input, context):
                yield provider.name, chunk
        except Exception as e:
            raise RuntimeError(f"{provider.name}: {e}") from e

    def _first_available_provider(self) -> tuple[BaseProvider | None, list[str]]:
        routes = self.config.model_routes()
        providers_cfg = routes.get("providers", {})
        errors: list[str] = []
        for provider_name in routes.get("selection_order", ["ollama", "huggingface", "openai"]):
            cfg = providers_cfg.get(provider_name, {})
            if cfg.get("enabled") is False:
                continue
            provider = self._make_provider(provider_name, cfg)
            if provider is None:
                errors.append(f"{provider_name}: provider not recognized or not configured")
                continue
            return provider, errors
        return None, errors

    def _make_provider(self, name: str, cfg: dict[str, Any]) -> BaseProvider | None:
        if name == "ollama":
            return OllamaProvider(cfg.get("base_url", "http://127.0.0.1:11434"), cfg.get("model", "qwen3:4b"))
        if name == "huggingface":
            model = cfg.get("model")
            if not model:
                return None
            return HuggingFaceEndpointProvider(model)
        if name == "openai":
            return OpenAIProvider(cfg.get("model", "gpt-4o-mini"))
        return None

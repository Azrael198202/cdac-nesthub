from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.llm.provider_handlers.ollama_handler import OllamaProviderHandler
from ai_core.llm.provider_handlers.openai_handler import OpenAIProviderHandler
from ai_core.llm.provider_handlers.openai_compatible_handler import OpenAICompatibleProviderHandler


class ProviderHandlerRegistry:
    def __init__(self) -> None:
        handlers = [
            OllamaProviderHandler(),
            OpenAIProviderHandler(),
            OpenAICompatibleProviderHandler(),
        ]
        self.handlers = {handler.provider_type: handler for handler in handlers}

    def get(self, provider_type: str):
        handler = self.handlers.get(provider_type)
        if not handler:
            supported = ", ".join(sorted(self.handlers.keys()))
            raise ProviderUnavailableError(f"Unsupported provider type: {provider_type}. Supported provider types: {supported}")
        return handler

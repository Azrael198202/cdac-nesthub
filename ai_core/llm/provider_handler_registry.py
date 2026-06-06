from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.llm.provider_handlers.universal_model_handler import UniversalModelProviderHandler


class ProviderHandlerRegistry:
    """Protocol-driven provider registry.

    Legacy provider type names are aliases to the universal handler. New provider
    behavior should be configured or runtime-generated, not hardcoded as a new
    ai_core adapter file.
    """

    def __init__(self) -> None:
        self.universal = UniversalModelProviderHandler()
        self.handlers = {
            "universal_model": self.universal,
            "openai": self.universal,
            "openai_compatible": self.universal,
            "ollama": self.universal,
        }

    def get(self, provider_type: str):
        handler = self.handlers.get(provider_type or "universal_model")
        if not handler:
            raise ProviderUnavailableError(
                f"Unsupported provider type: {provider_type}. Configure a universal protocol or register a runtime-generated adapter."
            )
        return handler

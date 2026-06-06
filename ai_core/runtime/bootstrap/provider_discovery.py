from __future__ import annotations

from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS


class ProviderDiscovery:
    """Reads currently configured model providers.

    Discovery is config-driven. This class does not assume vendor names or
    domain tasks; it only exposes the providers that the runtime already knows.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()

    def discover(self) -> dict[str, Any]:
        config = self.loader.load_yaml(RUNTIME_CONFIGS / "models" / "providers.yaml")
        providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
        routes = config.get("routes") if isinstance(config.get("routes"), dict) else {}
        normalized: dict[str, Any] = {}
        for name, provider in providers.items():
            if not isinstance(provider, dict):
                continue
            normalized[str(name)] = {
                "enabled": bool(provider.get("enabled", False)),
                "type": provider.get("type"),
                "protocol": provider.get("protocol"),
                "model": provider.get("model"),
                "capabilities": provider.get("capabilities") or [],
                "model_tags": provider.get("model_tags") or [],
                "fallback_models": provider.get("fallback_models") or [],
                "available_local_models": provider.get("available_local_models") or [],
            }
        return {
            "providers": normalized,
            "routes": routes,
            "default_route": config.get("default_route") or [],
            "policy": config.get("policy") if isinstance(config.get("policy"), dict) else {},
        }

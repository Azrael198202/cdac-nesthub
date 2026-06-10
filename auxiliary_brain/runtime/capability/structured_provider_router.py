from __future__ import annotations

from typing import Any


class StructuredProviderRouter:
    """Generic placeholder for runtime-generated structured providers.

    The source package contains no domain provider. Runtime-generated tools may
    register structured providers and declare this mode in contracts.
    """

    def has_provider(self, *, step: dict[str, Any], capability: str) -> bool:
        providers = step.get("structured_providers")
        return isinstance(providers, list) and bool(providers)

    def select(self, *, step: dict[str, Any], capability: str) -> dict[str, Any] | None:
        providers = step.get("structured_providers")
        if isinstance(providers, list):
            for item in providers:
                if isinstance(item, dict):
                    return item
        return None

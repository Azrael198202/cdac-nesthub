from __future__ import annotations

from typing import Any


class FallbackPolicy:
    """Generic fallback decision helper."""

    def allowed(self, attempted_mode: str, next_mode: str, policy: dict[str, Any] | None = None) -> bool:
        policy = policy or {}
        blocked = {str(x) for x in policy.get("disabled_execution_modes", []) if str(x).strip()}
        if next_mode in blocked:
            return False
        explicit = policy.get("fallback_modes")
        if isinstance(explicit, list) and explicit:
            return next_mode in {str(x) for x in explicit}
        return True

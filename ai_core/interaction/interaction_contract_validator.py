from __future__ import annotations

from typing import Any


class InteractionContractValidator:
    """Validate frontend interaction contracts without domain knowledge."""

    def is_actionable(self, contract: dict[str, Any] | None) -> bool:
        if not isinstance(contract, dict):
            return False
        fields = contract.get("fields")
        if isinstance(fields, list):
            return bool(fields)
        if isinstance(fields, dict):
            return bool(fields)
        return False

    def validate_or_none(self, contract: dict[str, Any] | None) -> dict[str, Any] | None:
        return contract if self.is_actionable(contract) else None

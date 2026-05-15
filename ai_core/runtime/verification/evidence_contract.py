from __future__ import annotations

from typing import Any


class EvidenceContractValidator:
    """Validates generic structured evidence before synthesis."""

    REQUIRED = ("source_url", "facts")

    def validate(self, material: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        for key in self.REQUIRED:
            if key not in material and key not in (material.get("content") or {}):
                errors.append(f"missing_{key}")
        facts = material.get("facts") or (material.get("content") or {}).get("facts")
        if not isinstance(facts, list) or not facts:
            errors.append("empty_facts")
        return {"passed": not errors, "errors": errors}

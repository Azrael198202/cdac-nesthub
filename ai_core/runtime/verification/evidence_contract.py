from __future__ import annotations

from typing import Any

from ai_core.runtime.semantic import RuntimeSemanticContractEngine


class EvidenceContractValidator:
    """Validates generic structured evidence before synthesis.

    Validation is contract-driven. Domain-specific expectations must be supplied
    by runtime-generated contracts, not by core source code.
    """

    REQUIRED = ("source_url", "facts")

    def __init__(self) -> None:
        self.engine = RuntimeSemanticContractEngine()

    def validate(self, material: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        for key in self.REQUIRED:
            if key not in material and key not in (material.get("content") or {}):
                errors.append(f"missing_{key}")
        facts = material.get("facts") or (material.get("content") or {}).get("facts")
        if not isinstance(facts, list) or not facts:
            errors.append("empty_facts")
            verified: list[dict[str, Any]] = []
        else:
            verified = self.engine.verify_facts(facts, state=material, material=material)
            if not verified:
                errors.append("no_verified_facts")
        return {"passed": not errors, "errors": errors, "verified_fact_count": len(verified)}

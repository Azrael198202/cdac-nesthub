from __future__ import annotations

from typing import Any


class SourceTrustEngine:
    """Assigns generic trust levels to evidence material."""

    TRUST_ORDER = {
        "runtime_native": 4,
        "structured_provider": 3,
        "verified_external": 2,
        "external_content": 1,
        "unknown": 0,
    }

    def classify(self, material: dict[str, Any] | None = None, fact: dict[str, Any] | None = None) -> str:
        material = material or {}
        fact = fact or {}
        source = str(material.get("source") or fact.get("source") or "").casefold()
        provenance = material.get("provenance") if isinstance(material.get("provenance"), dict) else {}
        claims = provenance.get("execution_claims") if isinstance(provenance.get("execution_claims"), dict) else {}

        if source.startswith("runtime_native") or fact.get("source_level") == "runtime_native":
            return "runtime_native"
        if material.get("structured") is True or fact.get("structured") is True:
            return "structured_provider"
        if claims.get("live_verification_passed") or claims.get("evidence_quality_passed"):
            return "verified_external"
        if str(fact.get("source_url") or material.get("source_url") or "").startswith(("http://", "https://")):
            return "external_content"
        return "unknown"

    def allowed(self, level: str, contract: dict[str, Any] | None = None) -> bool:
        contract = contract or {}
        allowed_levels = contract.get("allowed_source_levels")
        if not isinstance(allowed_levels, list) or not allowed_levels:
            allowed_levels = ["runtime_native", "structured_provider", "verified_external", "external_content", "unknown"]
        return level in set(str(x) for x in allowed_levels)

    def rank(self, level: str) -> int:
        return self.TRUST_ORDER.get(level, 0)

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import PROJECT_ROOT
from ai_core.runtime.semantic.constraint_engine import ConstraintEngine
from ai_core.runtime.semantic.fact_type_inferencer import FactTypeInferencer
from ai_core.runtime.semantic.source_trust_engine import SourceTrustEngine


class RuntimeSemanticContractEngine:
    """Validates facts using runtime-generated semantic contracts.

    Contracts are loaded from runtime/generated/contracts. Source code remains
    generic: it applies semantic types, constraints, source policies, and output
    eligibility without knowing domain-specific fields.
    """

    def __init__(self, contract_dir: Path | None = None) -> None:
        self.contract_dir = contract_dir or (PROJECT_ROOT / "runtime" / "generated" / "contracts")
        self.inferencer = FactTypeInferencer()
        self.constraints = ConstraintEngine()
        self.source_trust = SourceTrustEngine()

    def verify_facts(self, facts: list[dict[str, Any]], *, state: dict[str, Any] | None = None, material: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        contract = self.load_contract(state or {})
        verified: list[dict[str, Any]] = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            enriched = self.inferencer.infer(fact)
            source_level = self.source_trust.classify(material=material or {}, fact=enriched)
            enriched["source_level"] = source_level
            source_allowed = self.source_trust.allowed(source_level, contract)
            validation = self.constraints.validate(enriched, contract)
            enriched["semantic_validation"] = validation
            enriched["verified"] = bool(source_allowed and validation.get("passed"))
            if not source_allowed:
                enriched.setdefault("semantic_validation", {}).setdefault("errors", []).append("source_level_not_allowed")
            if enriched["verified"]:
                verified.append(enriched)
        return self._sort_and_limit(verified)

    def load_contract(self, state: dict[str, Any]) -> dict[str, Any]:
        inline = self._inline_contract(state)
        if inline:
            return inline
        merged: dict[str, Any] = {}
        if self.contract_dir.exists():
            for path in sorted(self.contract_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(data, dict):
                    merged = self._merge(merged, data)
        return merged

    def _inline_contract(self, state: dict[str, Any]) -> dict[str, Any]:
        for key in ("semantic_contract", "runtime_semantic_contract", "output_contract"):
            value = state.get(key) if isinstance(state, dict) else None
            if isinstance(value, dict):
                return value
        runtime = state.get("runtime") if isinstance(state, dict) else None
        if isinstance(runtime, dict):
            value = runtime.get("semantic_contract")
            if isinstance(value, dict):
                return value
        return {}

    def _merge(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        result = dict(left)
        for key, value in right.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._merge(result[key], value)
            elif isinstance(value, list) and isinstance(result.get(key), list):
                result[key] = [*result[key], *value]
            else:
                result[key] = value
        return result

    def _sort_and_limit(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def score(item: dict[str, Any]) -> tuple[int, float]:
            return (self.source_trust.rank(str(item.get("source_level") or "unknown")), float(item.get("confidence") or 0.0))
        facts.sort(key=score, reverse=True)
        return facts[:24]

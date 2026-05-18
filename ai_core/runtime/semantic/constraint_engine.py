from __future__ import annotations

from typing import Any


class ConstraintEngine:
    """Applies runtime-declared and generic semantic constraints.

    Core code only executes constraint objects. It does not contain business
    field names. Built-in constraints are generic semantic safety rules that are
    independent of any vertical domain.
    """

    DEFAULT_CONSTRAINTS = {
        "bounded_ratio": {"min": 0.0, "max": 100.0},
        "coordinate": {"allow_as_observed_output": False},
    }

    def validate(self, fact: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
        semantic_type = str(fact.get("semantic_type") or "text")
        constraints = dict(self.DEFAULT_CONSTRAINTS.get(semantic_type, {}))
        constraints.update(self._contract_constraints(semantic_type, contract or {}))

        errors: list[str] = []
        warnings: list[str] = []

        if constraints.get("allow_as_observed_output") is False:
            errors.append("semantic_type_not_allowed_as_observed_output")

        if "min" in constraints or "max" in constraints:
            number = self._number(fact.get("value"))
            if number is None:
                errors.append("numeric_value_required")
            else:
                if "min" in constraints and number < float(constraints["min"]):
                    errors.append("value_below_minimum")
                if "max" in constraints and number > float(constraints["max"]):
                    errors.append("value_above_maximum")

        minimum_confidence = constraints.get("minimum_confidence")
        if minimum_confidence is not None:
            try:
                if float(fact.get("confidence") or 0.0) < float(minimum_confidence):
                    warnings.append("low_confidence")
            except Exception:
                warnings.append("confidence_unreadable")

        passed = not errors
        return {
            "passed": passed,
            "errors": errors,
            "warnings": warnings,
            "constraints_applied": constraints,
        }

    def _contract_constraints(self, semantic_type: str, contract: dict[str, Any]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        type_constraints = contract.get("semantic_type_constraints")
        if isinstance(type_constraints, dict) and isinstance(type_constraints.get(semantic_type), dict):
            output.update(type_constraints[semantic_type])
        generic = contract.get("generic_constraints")
        if isinstance(generic, dict):
            output.update(generic)
        return output

    def _number(self, value: Any) -> float | None:
        try:
            return float(str(value).strip())
        except Exception:
            return None

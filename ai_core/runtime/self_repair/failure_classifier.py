from __future__ import annotations

from typing import Any

from .contracts import FailureReport


class FailureClassifier:
    """Classifies runtime failures using structural signals only."""

    def classify(self, report: FailureReport | dict[str, Any]) -> dict[str, Any]:
        r = report.to_dict() if isinstance(report, FailureReport) else dict(report or {})
        text = " ".join(
            str(r.get(k) or "") for k in ["stage", "status", "message", "error_type"]
        ).casefold()
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        expected = r.get("expected_contract") if isinstance(r.get("expected_contract"), dict) else {}
        actual = r.get("actual_material") if isinstance(r.get("actual_material"), dict) else {}
        state = r.get("runtime_state") if isinstance(r.get("runtime_state"), dict) else {}

        if self._has_schema_signal(text, payload, expected):
            category = "schema_mismatch"
            repairable = True
        elif self._has_variable_signal(text, payload, actual, state):
            category = "unresolved_variable_binding"
            repairable = True
        elif self._has_parameter_signal(text, payload, expected, actual, state):
            category = "missing_or_misbound_parameter"
            repairable = True
        elif self._has_state_signal(text, payload, state):
            category = "state_or_checkpoint_inconsistency"
            repairable = True
        elif self._has_verification_signal(text, payload, actual):
            category = "verification_material_missing"
            repairable = False
        elif self._has_execution_signal(text, payload):
            category = "execution_failure_unknown"
            repairable = False
        else:
            category = "unknown_failure"
            repairable = False

        return {
            "category": category,
            "repairable_by_deterministic_engine": repairable,
            "requires_web_evidence": category in {"execution_failure_unknown", "unknown_failure"},
            "signals": {
                "stage": r.get("stage"),
                "status": r.get("status"),
                "error_type": r.get("error_type"),
            },
        }

    def _has_schema_signal(self, text: str, payload: dict[str, Any], expected: dict[str, Any]) -> bool:
        if any(x in text for x in ["schema", "validation", "expected", "type"]):
            return True
        return bool(expected.get("json_schema") or expected.get("input_schema")) and isinstance(payload.get("input"), dict)

    def _has_variable_signal(self, text: str, payload: dict[str, Any], actual: dict[str, Any], state: dict[str, Any]) -> bool:
        values = [payload, actual, state]
        if "variable" in text or "template" in text or "binding" in text:
            return True
        return any("{{" in str(v) and "}}" in str(v) for v in values)

    def _has_parameter_signal(self, text: str, payload: dict[str, Any], expected: dict[str, Any], actual: dict[str, Any], state: dict[str, Any]) -> bool:
        if any(x in text for x in ["missing", "parameter", "required", "argument"]):
            return True
        required = expected.get("required") or expected.get("required_parameters")
        if isinstance(required, list):
            available = {}
            for source in [payload, actual, state]:
                if isinstance(source, dict):
                    available.update(source.get("parameters", {}) if isinstance(source.get("parameters"), dict) else source)
            return any(k not in available for k in required)
        return False

    def _has_state_signal(self, text: str, payload: dict[str, Any], state: dict[str, Any]) -> bool:
        if any(x in text for x in ["checkpoint", "resume", "state", "pending"]):
            return True
        return bool(payload.get("checkpoint_id") or state.get("pending_checkpoint_id"))

    def _has_verification_signal(self, text: str, payload: dict[str, Any], actual: dict[str, Any]) -> bool:
        if any(x in text for x in ["verified", "evidence", "material"]):
            return True
        return payload.get("verified") is False or actual.get("verified") is False

    def _has_execution_signal(self, text: str, payload: dict[str, Any]) -> bool:
        if any(x in text for x in ["failed", "exception", "timeout", "refused", "reset", "unreachable"]):
            return True
        return bool(payload.get("exception") or payload.get("returncode") not in (None, 0))

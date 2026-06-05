from __future__ import annotations

import json
from typing import Any

from verification_brain.contracts import VerificationExpectation, VerificationResult


class RuntimeVerificationBrain:
    """Deterministic verification before model-based judgment.

    The first phase only includes generic checks that do not require domain
    knowledge and therefore can safely run in every workflow.
    """

    def verify(self, *, output: Any, expectation: VerificationExpectation | dict[str, Any] | None = None) -> VerificationResult:
        exp = expectation if isinstance(expectation, VerificationExpectation) else VerificationExpectation(
            name=str((expectation or {}).get("name") or "generic_runtime_expectation"),
            rules=(expectation or {}).get("rules") if isinstance((expectation or {}).get("rules"), dict) else {},
        )
        text = self._stringify(output)
        checks: list[dict[str, Any]] = []
        rules = exp.rules
        if rules.get("must_not_contain_unresolved_template", True):
            ok = "{{" not in text and "}}" not in text
            checks.append({"name": "must_not_contain_unresolved_template", "passed": ok})
        for key in rules.get("required_keys", []) if isinstance(rules.get("required_keys"), list) else []:
            ok = isinstance(output, dict) and key in output and output.get(key) not in (None, "")
            checks.append({"name": "required_key", "key": key, "passed": ok})
        accepted = rules.get("accepted_statuses")
        if isinstance(accepted, list) and accepted:
            status = output.get("status") if isinstance(output, dict) else None
            checks.append({"name": "accepted_status", "status": status, "passed": status in accepted})
        passed = all(check.get("passed") for check in checks) if checks else True
        return VerificationResult(passed=passed, status="verified" if passed else "verification_failed", checks=checks)

    def _stringify(self, output: Any) -> str:
        if isinstance(output, str):
            return output
        try:
            return json.dumps(output, ensure_ascii=False, default=str)
        except Exception:
            return str(output)

from __future__ import annotations

from typing import Any


class ExecutionContinuationCoordinator:
    """Generic continuation policy after an execution candidate is rejected.

    The coordinator is domain-neutral. It does not know what the user asked for;
    it only decides whether a failed or unverified candidate should be treated as
    terminal, or whether the runtime should continue with evidence-backed
    alternatives already available in discovery results.
    """

    CONTINUABLE_ERROR_CODES = {
        "missing_evidence_proof",
        "generated_result_missing_evidence",
        "synthetic_or_unverified",
        "unverified_output",
        "module_execution_failed",
        "tool_execution_failed",
    }

    def should_continue_with_evidence(self, result: dict[str, Any] | None) -> bool:
        if not isinstance(result, dict):
            return True
        if result.get("status") != "error":
            return False
        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        code = str(error.get("code") or result.get("code") or "").strip()
        if code in self.CONTINUABLE_ERROR_CODES:
            return True
        verification = result.get("data", {}).get("verification") if isinstance(result.get("data"), dict) else None
        if isinstance(verification, dict) and verification.get("passed") is False:
            return True
        return False

    def has_evidence_candidates(self, discovery: dict[str, Any] | None) -> bool:
        if not isinstance(discovery, dict):
            return False
        for key in ("documents", "documentation_evidence", "selected_evidence", "web_results", "web_evidence"):
            value = discovery.get(key)
            if isinstance(value, list) and value:
                return True
        result = discovery.get("result") if isinstance(discovery.get("result"), dict) else {}
        for key in ("documents", "documentation_evidence", "selected_evidence", "web_results", "web_evidence"):
            value = result.get(key)
            if isinstance(value, list) and value:
                return True
        return False

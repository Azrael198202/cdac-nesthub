from __future__ import annotations

from enum import Enum
from typing import Any


class FailureKind(str, Enum):
    FETCH_FAILED = "fetch_failed"
    EXTRACT_FAILED = "extract_failed"
    MATERIALIZATION_FAILED = "materialization_failed"
    VERIFICATION_FAILED = "verification_failed"
    ROUTING_FAILED = "routing_failed"
    SYNTHESIS_FAILED = "synthesis_failed"
    EXECUTION_FAILED = "execution_failed"


class FailureClassifier:
    def classify(self, payload: dict[str, Any] | None) -> FailureKind:
        if not isinstance(payload, dict):
            return FailureKind.EXECUTION_FAILED
        code = str(payload.get("code") or payload.get("status") or payload.get("reason") or "").lower()
        if "fetch" in code:
            return FailureKind.FETCH_FAILED
        if "extract" in code or "parse" in code:
            return FailureKind.EXTRACT_FAILED
        if "material" in code:
            return FailureKind.MATERIALIZATION_FAILED
        if "verify" in code or "evidence" in code:
            return FailureKind.VERIFICATION_FAILED
        if "route" in code:
            return FailureKind.ROUTING_FAILED
        if "synth" in code:
            return FailureKind.SYNTHESIS_FAILED
        return FailureKind.EXECUTION_FAILED

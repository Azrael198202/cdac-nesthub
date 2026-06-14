from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ai_core.utils.safe_json import make_json_safe


@dataclass
class RuntimeSerializationValidationResult:
    passed: bool
    repaired: bool = False
    value: Any = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


class RuntimeSerializationValidator:
    """Validate and repair runtime payloads before they cross layer boundaries.

    This validator is generic.  It does not inspect business semantics, task
    names, tool names, or domain words.  Its only responsibility is to keep
    runtime artifacts JSON-safe so later verification, tracing, template
    binding, SSE, and final synthesis cannot crash on Python runtime objects.
    """

    def validate_and_repair(self, value: Any) -> RuntimeSerializationValidationResult:
        try:
            json.dumps(value, ensure_ascii=False)
            return RuntimeSerializationValidationResult(passed=True, repaired=False, value=value)
        except Exception as exc:
            repaired = make_json_safe(value)
            try:
                json.dumps(repaired, ensure_ascii=False)
                return RuntimeSerializationValidationResult(
                    passed=True,
                    repaired=True,
                    value=repaired,
                    findings=[{"reason": "runtime_payload_was_not_json_serializable", "error": str(exc)}],
                    error=str(exc),
                )
            except Exception as second_exc:
                return RuntimeSerializationValidationResult(
                    passed=False,
                    repaired=False,
                    value={"serialization_failure": str(second_exc), "original_error": str(exc)},
                    findings=[{"reason": "runtime_payload_serialization_repair_failed", "error": str(second_exc)}],
                    error=str(second_exc),
                )

from __future__ import annotations

from pathlib import Path
from typing import Any

from .sandbox_validator import RuntimeCapabilitySandboxValidator


class RuntimeCapabilityRegistryManager:
    """Registration guard for auxiliary_brain capability acquisition."""

    REGISTERED_STATUS = "registered"
    BLUEPRINT_STATUSES = {"blueprint_generated", "sandbox_failed", "not_registered"}

    def __init__(self) -> None:
        self.validator = RuntimeCapabilitySandboxValidator()

    def assert_registerable(self, artifact_dir: str | Path) -> dict[str, Any]:
        decision = self.validator.validate_registration_quality(artifact_dir)
        if not decision.get("passed"):
            return {"safe_to_register": False, "status": str(decision.get("status") or "not_registered"), "reason": str(decision.get("reason") or "artifact_not_registerable"), "validation": decision}
        return {"safe_to_register": True, "status": self.REGISTERED_STATUS, "validation": decision}

    def normalize_status(self, *, generated: bool, sandbox_passed: bool, registered: bool) -> str:
        if registered:
            return self.REGISTERED_STATUS
        if not generated:
            return "not_registered"
        if not sandbox_passed:
            return "sandbox_failed"
        return "not_registered"

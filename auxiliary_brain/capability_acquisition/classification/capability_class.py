from __future__ import annotations

from enum import Enum


class CapabilityClass(str, Enum):
    """Neutral acquisition classes for runtime capability generation."""

    RUNTIME_NATIVE = "runtime_native"
    DEPENDENCY_BACKED = "dependency_backed"
    EXTERNAL_EVIDENCE_REQUIRED = "external_evidence_required"

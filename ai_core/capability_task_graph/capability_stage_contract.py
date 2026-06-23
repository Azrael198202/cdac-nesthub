from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CapabilityStageContract:
    stage: str
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    validation_contract: dict[str, Any] = field(default_factory=dict)

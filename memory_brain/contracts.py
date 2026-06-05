from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MemoryRecord:
    """A generic runtime memory record.

    The record stores what the runtime learned, not domain-specific rules. It is
    safe to index by structural keys such as component, category, and outcome.
    """

    memory_type: str
    category: str
    summary: str
    component: str = ""
    outcome: str = ""
    confidence: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

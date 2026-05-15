from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResultMaterial:
    """Generic runtime material collected before final user-facing synthesis."""

    source: str
    status: str
    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "content": self.content,
            "metadata": self.metadata,
            "provenance": self.provenance,
            "quality": self.quality,
        }

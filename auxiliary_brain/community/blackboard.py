from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class BlackboardEntry:
    key: str
    owner_id: str
    value: Any
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "owner_id": self.owner_id,
            "value": self.value,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


class RuntimeBlackboard:
    """Shared neutral state for generated agents."""

    def __init__(self) -> None:
        self._entries: dict[str, BlackboardEntry] = {}

    def put(self, key: str, owner_id: str, value: Any, metadata: dict[str, Any] | None = None) -> None:
        self._entries[key] = BlackboardEntry(
            key=key,
            owner_id=owner_id,
            value=value,
            metadata=metadata or {},
        )

    def get(self, key: str, default: Any = None) -> Any:
        entry = self._entries.get(key)
        return default if entry is None else entry.value

    def snapshot(self) -> dict[str, Any]:
        return {key: entry.to_dict() for key, entry in self._entries.items()}

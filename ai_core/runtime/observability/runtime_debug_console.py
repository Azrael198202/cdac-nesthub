from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RuntimeEvent:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "payload": self.payload, "timestamp": self.timestamp}


class RuntimeDebugConsole:
    """In-memory observability console for deterministic tests and UI display."""

    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    def record(self, name: str, **payload: Any) -> None:
        self.events.append(RuntimeEvent(name=name, payload=payload))

    def timeline(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events]

    def assert_seen(self, *names: str) -> bool:
        actual = [event.name for event in self.events]
        return all(name in actual for name in names)

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvidenceRequest:
    """Generic request for runtime evidence.

    The request is intentionally task/capability agnostic. Callers provide
    structural identifiers and optional time bounds; the evidence engine decides
    which files and trace snippets are relevant.
    """

    run_id: str = ""
    task_name: str = ""
    participant_id: str = ""
    event_name: str = ""
    started_at: str = ""
    ended_at: str = ""
    max_lines_per_file: int = 300

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceItem:
    source: str
    kind: str
    matched: bool
    lines: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidencePackage:
    request: EvidenceRequest
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    items: list[EvidenceItem] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def add_item(self, item: EvidenceItem) -> None:
        self.items.append(item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "collected_at": self.collected_at,
            "items": [item.to_dict() for item in self.items],
            "summary": self.summary,
        }


def safe_read_lines(path: Path, *, max_lines: int = 300) -> list[str]:
    try:
        if not path.exists() or not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if max_lines > 0 and len(lines) > max_lines:
            return lines[-max_lines:]
        return lines
    except Exception as exc:  # pragma: no cover - defensive evidence path
        return [f"<evidence_read_error path={path} error={type(exc).__name__}: {exc}>"]

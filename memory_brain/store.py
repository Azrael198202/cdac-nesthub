from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED
from memory_brain.contracts import MemoryRecord


class RuntimeMemoryStore:
    """Append-only memory store for runtime experience.

    It is intentionally simple in this phase so existing runtime behavior does
    not change. Later, this can be replaced with vector/database backends behind
    the same interface.
    """

    def __init__(self, *, root: Path | None = None) -> None:
        self.root = root or (RUNTIME_GENERATED / "memory_brain")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "runtime_experience.jsonl"

    def remember(self, record: MemoryRecord | dict[str, Any]) -> dict[str, Any]:
        data = record.to_dict() if isinstance(record, MemoryRecord) else dict(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
        return {"ok": True, "status": "memory_recorded", "path": str(self.path), "record": data}

    def recall(self, *, category: str = "", component: str = "", limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            if category and str(item.get("category")) != category:
                continue
            if component and str(item.get("component")) != component:
                continue
            records.append(item)
        return records[-max(1, limit):]

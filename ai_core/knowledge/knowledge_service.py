from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.runtime.paths import RUNTIME_DIR
from ai_core.runtime.file_store import FileStore


class KnowledgeService:
    def __init__(self) -> None:
        self.store = FileStore()
        self.path = RUNTIME_DIR / "knowledge/cases/cases.jsonl"

    def search(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        terms = {t.lower() for t in text.split() if len(t) > 3}
        scored = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            hay = json.dumps(item, ensure_ascii=False).lower()
            score = sum(1 for t in terms if t in hay)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored[:limit]]

    def save_case(self, item: dict[str, Any]) -> None:
        self.store.append_jsonl(self.path, item)

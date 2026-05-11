from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_core.runtime.paths import RUNTIME_DIR
from ai_core.runtime.file_store import FileStore


class ConversationStore:
    def __init__(self) -> None:
        self.store = FileStore()
        self.path = RUNTIME_DIR / "knowledge/conversation.jsonl"

    def append(self, role: str, content: str, meta: dict[str, Any] | None = None) -> None:
        self.store.append_jsonl(self.path, {
            "time": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "content": content,
            "meta": meta or {},
        })

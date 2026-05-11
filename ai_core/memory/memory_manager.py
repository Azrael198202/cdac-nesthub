from __future__ import annotations

from ai_core.config.io import append_jsonl, read_json, write_json
from ai_core.config.paths import RUNTIME_MEMORY_DIR


class MemoryManager:
    def add_message(self, role: str, content: str) -> None:
        append_jsonl(RUNTIME_MEMORY_DIR / "conversation.jsonl", {"role": role, "content": content})

    def get_recent_text(self, limit: int = 10) -> str:
        path = RUNTIME_MEMORY_DIR / "conversation.jsonl"
        if not path.exists():
            return ""
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        return "\n".join(lines)

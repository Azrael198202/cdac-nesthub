from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ai_core.config.io import append_jsonl, read_json, write_json
from ai_core.config.paths import RUNTIME_DATASETS_DIR, RUNTIME_KNOWLEDGE_DIR


class KnowledgeService:
    def __init__(self) -> None:
        self.methods_dir = RUNTIME_KNOWLEDGE_DIR / "methods"
        self.success_dir = RUNTIME_KNOWLEDGE_DIR / "success_cases"

    def _key(self, text: str) -> str:
        normalized = " ".join(text.lower().split())
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]

    def find_similar_method(self, user_text: str) -> dict[str, Any] | None:
        # Minimal keyword retrieval. Replace later with vector DB through runtime config.
        lower = user_text.lower()
        for path in self.methods_dir.glob("*.json"):
            data = read_json(path, {})
            kws = data.get("keywords", [])
            if any(k.lower() in lower for k in kws):
                return data
        return None

    def save_method(self, name: str, data: dict[str, Any]) -> Path:
        path = self.methods_dir / f"{name}.json"
        write_json(path, data)
        return path

    def save_success_case(self, user_text: str, data: dict[str, Any]) -> Path:
        path = self.success_dir / f"case_{self._key(user_text)}.json"
        write_json(path, data)
        append_jsonl(RUNTIME_DATASETS_DIR / "finetune.jsonl", {
            "input": user_text,
            "output": data.get("final_answer", ""),
            "trace": data.get("trace_id"),
        })
        return path

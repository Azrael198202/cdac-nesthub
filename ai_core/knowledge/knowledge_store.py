from __future__ import annotations
import json
import time
from pathlib import Path
from ai_core.config.paths import RUNTIME_KNOWLEDGE_DIR, RUNTIME_DATASETS_DIR


class KnowledgeStore:
    def save_case(self, case: dict) -> Path:
        RUNTIME_KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        path = RUNTIME_KNOWLEDGE_DIR / f"case_{int(time.time()*1000)}.json"
        path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def append_finetune(self, item: dict) -> None:
        path = RUNTIME_DATASETS_DIR / "finetune.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

from ai_core.config.paths import RUNTIME_KNOWLEDGE
import json
from datetime import datetime


class KnowledgeService:
    def search(self, query: str) -> list[dict]:
        return []

    def save_success_case(self, run_id: str, data: dict) -> None:
        RUNTIME_KNOWLEDGE.mkdir(parents=True, exist_ok=True)
        p = RUNTIME_KNOWLEDGE / "success_cases.jsonl"
        record = {"run_id": run_id, "created_at": datetime.utcnow().isoformat(), "data": data}
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

import json
from datetime import datetime
from ai_core.config.paths import RUNTIME_TRACES


class TraceWriter:
    def write(self, run_id: str, event: dict) -> None:
        day = datetime.now().strftime("%Y%m%d")
        d = RUNTIME_TRACES / day
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{run_id}.jsonl"
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

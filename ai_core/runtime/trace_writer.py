from datetime import datetime

from ai_core.config.paths import RUNTIME_TRACES
from ai_core.utils.safe_json import safe_json_dumps


class TraceWriter:
    def write(self, run_id: str, event: dict) -> None:
        d = RUNTIME_TRACES / datetime.now().strftime("%Y%m%d")
        d.mkdir(parents=True, exist_ok=True)
        with (d / f"{run_id}.jsonl").open("a", encoding="utf-8") as f:
            f.write(safe_json_dumps(event) + "\n")

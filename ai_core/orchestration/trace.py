from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from ai_core.config.io import write_json
from ai_core.config.paths import RUNTIME_TRACES_DIR


class TraceRecorder:
    def __init__(self) -> None:
        self.trace_id = datetime.now().strftime("%Y%m%d") + "_" + uuid4().hex[:8]
        self.events: list[dict] = []

    def add(self, step: str, status: str, data: dict) -> None:
        self.events.append({"step": step, "status": status, "data": data})

    def save(self) -> str:
        path = RUNTIME_TRACES_DIR / f"request_{self.trace_id}.json"
        write_json(path, {"trace_id": self.trace_id, "events": self.events})
        return str(path)

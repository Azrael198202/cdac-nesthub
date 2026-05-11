from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
import json


@dataclass
class WorkflowEvent:
    type: str
    title: str
    message: str
    status: str = "running"
    data: Any = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["time"] = datetime.now(timezone.utc).isoformat()
        return d

    def to_sse(self) -> str:
        return "data: " + json.dumps(self.to_dict(), ensure_ascii=False) + "\n\n"

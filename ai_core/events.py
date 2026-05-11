from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
import json

@dataclass
class Event:
    type: str
    title: str
    message: str = ""
    data: dict[str, Any] | None = None

    def to_sse(self) -> str:
        payload = asdict(self)
        payload["ts"] = datetime.now(timezone.utc).isoformat()
        return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

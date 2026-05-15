from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_DIR


class TokenUsageLogger:
    """Provider-neutral token/latency logger."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (RUNTIME_DIR / "metrics" / "token_usage.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: dict[str, Any]) -> None:
        safe = dict(record)
        safe.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(safe, ensure_ascii=False, default=str) + "\n")

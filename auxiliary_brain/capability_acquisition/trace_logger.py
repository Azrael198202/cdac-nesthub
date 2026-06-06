from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_TRACES


class CapabilityAcquisitionTraceLogger:
    """JSONL trace logger for ai_core -> auxiliary_brain capability acquisition.

    The logger is intentionally generic.  It records stage inputs/outputs and
    gate decisions without embedding any capability-specific rules.
    """

    def __init__(self, *, root: Path | None = None) -> None:
        self.root = root or (RUNTIME_TRACES / "capability_acquisition")

    def record(self, *, run_id: str, stage: str, status: str, payload: dict[str, Any] | None = None) -> None:
        safe_run_id = self._safe_name(run_id or "unknown_run")
        path = self.root / f"{safe_run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "stage": stage,
            "status": status,
            "payload": self._json_safe(payload or {}),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def write_snapshot(self, *, run_id: str, name: str, payload: dict[str, Any]) -> None:
        safe_run_id = self._safe_name(run_id or "unknown_run")
        safe_name = self._safe_name(name or "snapshot")
        path = self.root / safe_run_id / f"{safe_name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._json_safe(payload), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def _json_safe(self, value: Any) -> Any:
        try:
            json.dumps(value, ensure_ascii=False, default=str)
            return value
        except Exception:
            return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in str(value)).strip("_") or "unknown"

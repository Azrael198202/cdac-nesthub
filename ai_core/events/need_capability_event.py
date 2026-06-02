from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
import json

from ai_core.config.paths import RUNTIME_TRACES


@dataclass(frozen=True)
class NeedCapabilityEvent:
    """Generic ai_core -> auxiliary_brain capability request event.

    ai_core creates this event during workflow planning when a required runtime
    capability is not available. The event carries only generic planning
    metadata; acquisition, implementation, validation, and registration are
    owned by auxiliary_brain.
    """

    run_id: str
    required_capability: str
    available: bool = False
    source_stage: str = "workflow_planning"
    status: str = "needed"
    payload: dict[str, Any] | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        if data.get("payload") is None:
            data["payload"] = {}
        try:
            trace_dir = RUNTIME_TRACES / "need_capability_events"
            trace_dir.mkdir(parents=True, exist_ok=True)
            path = trace_dir / (str(self.run_id or "unknown") + ".json")
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass
        return data

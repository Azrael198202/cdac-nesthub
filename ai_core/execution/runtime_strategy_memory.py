from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_KNOWLEDGE
from ai_core.utils.safe_json import safe_json_dumps, make_json_safe


class RuntimeStrategyMemory:
    """Append-only memory for successful runtime execution strategies.

    Stored outside core under runtime/knowledge so the source tree remains
    reproducible and domain-neutral.
    """

    def __init__(self) -> None:
        self.path = RUNTIME_KNOWLEDGE / "successful_strategies.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record_success(self, *, capability: str, step: dict[str, Any], attempt: dict[str, Any] | None, result: dict[str, Any]) -> None:
        candidate = attempt.get("candidate") if isinstance(attempt, dict) and isinstance(attempt.get("candidate"), dict) else {}
        payload = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "capability": capability,
            "step_type": step.get("step_type") if isinstance(step, dict) else None,
            "required_capability": step.get("required_capability") if isinstance(step, dict) else None,
            "candidate": {
                "name": candidate.get("name"),
                "url": candidate.get("url") or candidate.get("official_documentation_url"),
                "source": candidate.get("source"),
                "tool_type": candidate.get("tool_type"),
                "score": candidate.get("score"),
            },
            "result_quality": (result.get("quality") or {}).get("evidence") if isinstance(result, dict) else None,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(safe_json_dumps(make_json_safe(payload)) + "\n")

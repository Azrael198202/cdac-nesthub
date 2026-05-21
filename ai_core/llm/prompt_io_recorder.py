from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_DIR


class PromptIORecorder:
    """Persist LLM stage prompt/response material for runtime debugging.

    This recorder is intentionally generic: it records runtime node metadata,
    prompts, schemas, provider identity, outputs, and errors. It does not make
    business/domain decisions and it is not used for routing.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or (RUNTIME_DIR / "traces" / "llm")

    def record(self, *, run_id: str, node_id: str | None, phase: str, payload: dict[str, Any]) -> str:
        safe_run_id = self._safe_name(run_id or "unknown_run")
        safe_node_id = self._safe_name(node_id or "unknown_node")
        safe_phase = self._safe_name(phase or "event")
        run_dir = self.base_dir / safe_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{int(time.time() * 1000)}_{safe_node_id}_{safe_phase}.json"
        path = run_dir / filename
        path.write_text(json.dumps(self._json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def _safe_name(self, value: str) -> str:
        text = str(value or "").strip() or "value"
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:120]

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._json_safe(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

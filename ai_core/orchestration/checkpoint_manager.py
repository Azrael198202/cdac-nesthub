from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_DIR


class CheckpointManager:
    """Generic persistent workflow checkpoint store.

    The core stores only generic workflow state:
    - run_id
    - user_input
    - workflow
    - state
    - next_index
    - status
    - approval_id
    """

    def __init__(self) -> None:
        self.dir = RUNTIME_DIR / "checkpoints"
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, run_id: str) -> Path:
        return self.dir / f"{run_id}.json"

    def save(self, checkpoint: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path(checkpoint["run_id"]).write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, run_id: str) -> dict[str, Any] | None:
        p = self.path(run_id)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def mark_completed(self, run_id: str) -> None:
        cp = self.load(run_id)
        if not cp:
            return
        cp["status"] = "completed"
        self.save(cp)

    def mark_rejected(self, run_id: str, comment: str = "") -> None:
        cp = self.load(run_id)
        if not cp:
            return
        cp["status"] = "rejected"
        cp["reject_comment"] = comment
        self.save(cp)

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import RepairAction


class StateRepairer:
    """Plans safe recovery for missing runtime state references."""

    def plan(self, *, runtime_state: dict[str, Any], storage_root: str | Path | None = None) -> list[RepairAction]:
        actions: list[RepairAction] = []
        if not isinstance(runtime_state, dict):
            return actions
        checkpoint_id = runtime_state.get("pending_checkpoint_id") or runtime_state.get("checkpoint_id")
        if checkpoint_id and not runtime_state.get("checkpoint_material"):
            recovered = self._find_checkpoint(str(checkpoint_id), storage_root)
            if recovered:
                actions.append(RepairAction(
                    action_type="checkpoint_material_recovery",
                    level="runtime_knowledge",
                    description="Recover missing checkpoint material from runtime storage.",
                    target_path="checkpoint_material",
                    before=None,
                    after=recovered,
                    safe_to_apply=True,
                    requires_validation=True,
                    confidence=0.84,
                    metadata={"checkpoint_id": checkpoint_id},
                ))
        return actions

    def apply(self, *, runtime_state: dict[str, Any], actions: list[RepairAction]) -> dict[str, Any]:
        out = dict(runtime_state or {})
        for action in actions:
            if action.action_type == "checkpoint_material_recovery":
                out[action.target_path] = action.after
        return out

    def _find_checkpoint(self, checkpoint_id: str, storage_root: str | Path | None) -> dict[str, Any] | None:
        if not storage_root:
            return None
        root = Path(storage_root)
        if not root.exists():
            return None
        for path in root.rglob("*.json"):
            if checkpoint_id in path.name:
                try:
                    import json
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
        return None

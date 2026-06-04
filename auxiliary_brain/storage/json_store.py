from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class JsonStore:
    def __init__(self, root: str | Path = "runtime") -> None:
        self.root = Path(root)

    def ensure_workspace(self) -> None:
        for relative in [
            "generated/agents",
            "generated/tasks",
            "generated/communities",
            "generated/results",
            "traces/agent_delegation",
            "deliveries",
        ]:
            path = self.root / relative
            path.mkdir(parents=True, exist_ok=True)
            keep = path / ".gitkeep"
            if not keep.exists():
                keep.write_text("", encoding="utf-8")

    def write_json(self, relative: str, payload: dict[str, Any]) -> Path:
        self.ensure_workspace()
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read_json(self, relative: str) -> dict[str, Any]:
        path = self.root / relative
        if not path.exists():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    def delete_json(self, relative: str) -> dict[str, Any]:
        path = self.root / relative
        if not path.exists() or not path.is_file():
            return {"ok": False, "status": "not_found", "path": str(path)}
        try:
            path.unlink()
            return {"ok": True, "status": "deleted", "path": str(path)}
        except Exception as exc:
            return {"ok": False, "status": "failed", "path": str(path), "error": str(exc)}

    def list_json(self, relative: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        self.ensure_workspace()
        path = self.root / relative
        out: list[dict[str, Any]] = []
        if not path.exists():
            return out
        if limit is None:
            try:
                limit = int(os.environ.get("AI_CORE_JSON_STORE_LIST_LIMIT", "300"))
            except Exception:
                limit = 300
        items = sorted(path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for item in items[: max(1, int(limit))]:
            try:
                loaded = json.loads(item.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    loaded.setdefault("_path", str(item))
                    out.append(loaded)
            except Exception:
                continue
        return out

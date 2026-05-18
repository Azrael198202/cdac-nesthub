from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class RuntimeScheduler:
    """Persistent scheduler registry for generated task graphs.

    This class stores activation records and due-state transitions. It does not
    contain domain actions; execution is delegated to the runtime executor.
    """

    ORIGIN = "auxiliary_brain"

    def __init__(self, runtime_root: str | Path = "runtime") -> None:
        self.runtime_root = Path(runtime_root)
        self.schedule_dir = self.runtime_root / "generated" / "schedules"
        self.instance_dir = self.runtime_root / "instances"
        self.schedule_dir.mkdir(parents=True, exist_ok=True)
        self.instance_dir.mkdir(parents=True, exist_ok=True)

    def register(self, *, graph_id: str, graph_path: str, activation: dict[str, Any]) -> dict[str, Any]:
        schedule_id = f"schedule_{uuid4().hex[:8]}"
        instance_id = f"instance_{uuid4().hex[:8]}"
        metadata = dict(activation.get("metadata") or {})
        scheduled_at = metadata.get("scheduled_at")
        status = "scheduled" if scheduled_at else "ready"
        record = {
            "schedule_id": schedule_id,
            "origin": self.ORIGIN,
            "graph_id": graph_id,
            "graph_path": graph_path,
            "activation": activation,
            "instance_id": instance_id,
            "status": status,
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        self._write(self.schedule_dir / f"{schedule_id}.json", record)
        instance = {
            "instance_id": instance_id,
            "origin": self.ORIGIN,
            "graph_id": graph_id,
            "schedule_id": schedule_id,
            "status": status,
            "created_at": self._now(),
            "updated_at": self._now(),
            "events": [{"type": "registered", "at": self._now(), "status": status}],
        }
        self._write(self.instance_dir / f"{instance_id}.json", instance)
        return {"schedule": record, "instance": instance}

    def due_records(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now().astimezone()
        records: list[dict[str, Any]] = []
        for path in self.schedule_dir.glob("*.json"):
            record = self._read(path)
            if record.get("status") not in {"scheduled", "ready", "running"}:
                continue
            scheduled_at = (record.get("activation") or {}).get("metadata", {}).get("scheduled_at")
            if not scheduled_at:
                if record.get("status") == "running":
                    records.append(record)
                continue
            try:
                due_at = datetime.fromisoformat(scheduled_at)
            except ValueError:
                continue
            if due_at <= now:
                records.append(record)
        return records

    def mark(self, schedule_id: str, status: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        path = self.schedule_dir / f"{schedule_id}.json"
        if not path.exists():
            return {"status": "missing", "schedule_id": schedule_id}
        record = self._read(path)
        record["status"] = status
        record["updated_at"] = self._now()
        if payload:
            record.setdefault("events", []).append({"type": status, "at": self._now(), "payload": payload})
        self._write(path, record)
        instance_id = record.get("instance_id")
        if instance_id:
            self._mark_instance(instance_id, status, payload or {})
        return record

    def _mark_instance(self, instance_id: str, status: str, payload: dict[str, Any]) -> None:
        path = self.instance_dir / f"{instance_id}.json"
        instance = self._read(path) if path.exists() else {"instance_id": instance_id, "origin": self.ORIGIN, "events": []}
        instance["status"] = status
        instance["updated_at"] = self._now()
        instance.setdefault("events", []).append({"type": status, "at": self._now(), "payload": payload})
        self._write(path, instance)

    def _read(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _now(self) -> str:
        return datetime.now().astimezone().isoformat()

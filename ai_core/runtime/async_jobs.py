from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4


class RuntimeAsyncJobStore:
    """Small process-local async job registry with durable JSON snapshots.

    It is intentionally domain-neutral: callers provide a coroutine factory and
    the store only records lifecycle, result, and error material.
    """

    def __init__(self, *, state_dir: Path | str = Path("runtime") / "traces" / "async_jobs") -> None:
        self.state_dir = Path(state_dir)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def submit(self, *, name: str, runner: Callable[[], Awaitable[dict[str, Any]]], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        job_id = f"job_{uuid4().hex[:16]}"
        now = self._now()
        record = {
            "job_id": job_id,
            "name": str(name or "runtime_job"),
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "metadata": metadata if isinstance(metadata, dict) else {},
            "result": None,
            "error": None,
        }
        self._jobs[job_id] = record
        self._write(record)
        self._tasks[job_id] = asyncio.create_task(self._run(job_id, runner))
        return {"ok": True, "status": "accepted", "job_id": job_id, "job": self.public(job_id)}

    def public(self, job_id: str) -> dict[str, Any] | None:
        record = self._jobs.get(job_id) or self._read(job_id)
        if not isinstance(record, dict):
            return None
        return record

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        items = list(self._jobs.values())
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            for path in self.state_dir.glob("job_*.json"):
                item = self._read(path.stem)
                if isinstance(item, dict) and item.get("job_id") not in {x.get("job_id") for x in items}:
                    items.append(item)
        except Exception:
            pass
        items.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
        return items[: max(1, int(limit or 50))]

    async def _run(self, job_id: str, runner: Callable[[], Awaitable[dict[str, Any]]]) -> None:
        record = self._jobs.get(job_id)
        if not record:
            return
        record["status"] = "running"
        record["started_at"] = self._now()
        record["updated_at"] = record["started_at"]
        self._write(record)
        try:
            result = await runner()
            record["result"] = result if isinstance(result, dict) else {"value": result}
            result_status = str((record["result"] or {}).get("status") or "completed")
            record["status"] = "failed" if result_status in {"failed", "error"} else "completed"
            record["finished_at"] = self._now()
            record["updated_at"] = record["finished_at"]
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = {"type": exc.__class__.__name__, "message": str(exc)}
            record["finished_at"] = self._now()
            record["updated_at"] = record["finished_at"]
        self._write(record)

    def _write(self, record: dict[str, Any]) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            (self.state_dir / f"{record.get('job_id')}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _read(self, job_id: str) -> dict[str, Any] | None:
        safe = Path(str(job_id)).name
        path = self.state_dir / f"{safe}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

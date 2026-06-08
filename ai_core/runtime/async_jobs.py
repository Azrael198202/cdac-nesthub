from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from ai_core.runtime.state import runtime_state_manager


class RuntimeAsyncJobStore:
    """Small process-local async job registry with durable JSON snapshots.

    It is intentionally domain-neutral: callers provide a coroutine factory and
    the store only records lifecycle, result, and error material.
    """

    def __init__(self, *, state_dir: Path | str = Path("runtime") / "traces" / "async_jobs") -> None:
        self.state_dir = Path(state_dir)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def submit(self, *, name: str, runner: Callable[[], Awaitable[dict[str, Any]]], metadata: dict[str, Any] | None = None, job_id: str | None = None) -> dict[str, Any]:
        job_id = str(job_id or f"job_{uuid4().hex[:16]}").strip() or f"job_{uuid4().hex[:16]}"
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
        runtime_state_manager.start_run(
            job_id,
            task_id=record["name"],
            title=f"Async runtime job: {record['name']}",
            metadata={"job_id": job_id, "metadata": record.get("metadata") or {}},
        )
        runtime_state_manager.emit(
            run_id=job_id,
            step_id="job.queue",
            level="user",
            kind="lifecycle",
            status="queued",
            title="Job accepted",
            message="The runtime job has been accepted and queued.",
            progress=5,
            output={"job_id": job_id, "name": record["name"]},
        )
        self._tasks[job_id] = asyncio.create_task(self._run(job_id, runner))
        return {"ok": True, "status": "accepted", "job_id": job_id, "state_run_id": job_id, "job": self.public(job_id)}

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
        runtime_state_manager.emit(
            run_id=job_id,
            step_id="job.run",
            level="user",
            kind="lifecycle",
            status="running",
            title="Job running",
            message="The async job worker has started execution.",
            method="async_worker",
            progress=15,
        )
        try:
            # Run the supplied runtime operation outside the FastAPI event loop.
            # Some runtime layers perform local model calls, filesystem work,
            # sandbox validation, installs, or other blocking operations.  If
            # those operations run directly inside the server loop, other pages
            # such as Runtime State Console cannot load until the job ends.
            result = await asyncio.to_thread(self._run_runner_in_private_loop, runner)
            record["result"] = result if isinstance(result, dict) else {"value": result}
            result_status = str((record["result"] or {}).get("status") or "completed")
            record["status"] = "failed" if result_status in {"failed", "error"} else "completed"
            record["finished_at"] = self._now()
            record["updated_at"] = record["finished_at"]
            runtime_state_manager.emit(
                run_id=job_id,
                step_id="job.queue",
                level="developer",
                kind="lifecycle",
                status="completed",
                title="Job accepted",
                message="The queued job was picked up by a worker.",
                progress=100,
            )
            runtime_state_manager.emit(
                run_id=job_id,
                step_id="job.run",
                level="user",
                kind="lifecycle",
                status=record["status"],
                title="Job running",
                message=f"The async job worker finished with status={record['status']}.",
                method="async_worker",
                progress=100,
            )
            runtime_state_manager.emit(
                run_id=job_id,
                step_id="job.result",
                level="user",
                kind="output",
                status=record["status"],
                title="Job result",
                message=f"Async job finished with status={record['status']}.",
                output={"result_status": result_status},
                progress=100,
            )
            runtime_state_manager.finish_run(job_id, status=record["status"], summary=f"Async job {record['status']}", output={"result_status": result_status})
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = {"type": exc.__class__.__name__, "message": str(exc)}
            record["finished_at"] = self._now()
            record["updated_at"] = record["finished_at"]
            runtime_state_manager.emit(
                run_id=job_id,
                step_id="job.error",
                level="developer",
                kind="error",
                status="failed",
                title="Job failed",
                message=str(exc),
                error=record["error"],
                progress=100,
            )
            runtime_state_manager.finish_run(job_id, status="failed", summary=str(exc), error=record["error"])
        self._write(record)

    def _run_runner_in_private_loop(self, runner: Callable[[], Awaitable[dict[str, Any]]]) -> Any:
        value = runner()
        if inspect.isawaitable(value):
            return asyncio.run(value)
        return value


    def close_non_terminal_jobs_on_startup(self, *, reason: str = "Runtime process restarted before the async worker finished.") -> int:
        active = {"queued", "running"}
        count = 0
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            paths = list(self.state_dir.glob("job_*.json"))
        except Exception:
            paths = []
        now = self._now()
        for path in paths:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(record, dict) or str(record.get("status") or "") not in active:
                continue
            record["status"] = "interrupted"
            record["updated_at"] = now
            record["finished_at"] = record.get("finished_at") or now
            record["error"] = {"type": "RuntimeRestart", "message": reason}
            self._jobs[str(record.get("job_id") or path.stem)] = record
            self._write(record)
            count += 1
        return count

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

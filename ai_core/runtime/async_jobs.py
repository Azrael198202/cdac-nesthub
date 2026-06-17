from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from ai_core.runtime.state import runtime_state_manager
from ai_core.runtime.lifecycle_settings import RuntimeLifecycleSettingsStore


class RuntimeAsyncJobStore:
    """Small process-local async job registry with durable JSON snapshots.

    It is intentionally domain-neutral: callers provide a coroutine factory and
    the store only records lifecycle, result, and error material.
    """

    def __init__(self, *, state_dir: Path | str = Path("runtime") / "traces" / "async_jobs") -> None:
        self.state_dir = Path(state_dir)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self.lifecycle_settings_store = RuntimeLifecycleSettingsStore()

    def submit(self, *, name: str, runner: Callable[[], Awaitable[dict[str, Any]]], metadata: dict[str, Any] | None = None, job_id: str | None = None, timeout_seconds: int | None = None) -> dict[str, Any]:
        job_id = str(job_id or f"job_{uuid4().hex[:16]}").strip() or f"job_{uuid4().hex[:16]}"
        now = self._now()
        record = {
            "job_id": job_id,
            "name": str(name or "runtime_job"),
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "metadata": metadata if isinstance(metadata, dict) else {},
            "timeout_seconds": self._resolve_timeout_seconds(timeout_seconds=timeout_seconds, metadata=metadata),
            "watchdog": {"enabled": True, "last_heartbeat_at": now, "stale_after_seconds": self._resolve_stale_seconds(metadata=metadata)},
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
        record = self._merge_durable_runtime_state(record)
        return self._recover_stale_running_job(record)

    def _merge_durable_runtime_state(self, record: dict[str, Any]) -> dict[str, Any]:
        """Recover visible job result from durable runtime_state after reload.

        WatchFiles/local reload can interrupt the process-local async worker while
        the delegated runtime already finished and wrote runtime_state.  The job
        snapshot should not hide that completed durable result.
        """
        job_id = str(record.get("job_id") or "")
        if not job_id:
            return record
        try:
            run = runtime_state_manager.get_run(job_id)
        except Exception:
            run = None
        if not isinstance(run, dict):
            return record
        run_status = str(run.get("status") or "")
        # Runtime state is the durable heartbeat for an isolated worker.
        # The async job snapshot is process-local and may not be updated while
        # the private worker is inside a long runtime stage, so polling this
        # endpoint must merge runtime_state.updated_at back into the job
        # watchdog.  This is generic lifecycle logic, not task-specific logic.
        run_updated = run.get("updated_at")
        if run_updated:
            watchdog = record.get("watchdog") if isinstance(record.get("watchdog"), dict) else {}
            if str(watchdog.get("last_heartbeat_at") or "") < str(run_updated):
                recovered = dict(record)
                watchdog = dict(watchdog)
                watchdog["last_heartbeat_at"] = run_updated
                recovered["watchdog"] = watchdog
                recovered["updated_at"] = run_updated
                self._jobs[job_id] = recovered
                self._write(recovered)
                record = recovered
        terminal = {"completed", "paused", "failed", "cancelled"}
        if run_status not in terminal:
            return record
        current = str(record.get("status") or "")
        if current in {"queued", "running", "interrupted"} or not record.get("result"):
            recovered = dict(record)
            recovered["status"] = run_status
            recovered["updated_at"] = run.get("updated_at") or recovered.get("updated_at")
            recovered["finished_at"] = recovered.get("finished_at") or run.get("ended_at") or run.get("updated_at")
            recovered["error"] = run.get("last_error") if run_status == "failed" else None
            recovered["result"] = recovered.get("result") or {
                "ok": run_status in {"completed", "paused"},
                "status": run_status,
                "run_id": job_id,
                "runtime_state": {"run_id": job_id, "state_url": f"/runtime-state?run_id={job_id}"},
                "final_answer": run.get("summary") or f"Runtime job {run_status}. See Runtime State Console for details.",
                "durable_recovered": True,
            }
            self._jobs[job_id] = recovered
            self._write(recovered)
            return recovered
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
        recovered_items = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("job_id") or "")
            if job_id and job_id in seen:
                continue
            if job_id:
                seen.add(job_id)
            recovered_items.append(self._recover_stale_running_job(self._merge_durable_runtime_state(item)))
        recovered_items.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
        return recovered_items[: max(1, int(limit or 50))]

    async def _run(self, job_id: str, runner: Callable[[], Awaitable[dict[str, Any]]]) -> None:
        record = self._jobs.get(job_id)
        if not record:
            return
        record["status"] = "running"
        record["started_at"] = self._now()
        record["updated_at"] = record["started_at"]
        watchdog = record.get("watchdog") if isinstance(record.get("watchdog"), dict) else {}
        watchdog["last_heartbeat_at"] = record["updated_at"]
        record["watchdog"] = watchdog
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
        heartbeat_task: asyncio.Task[Any] | None = None
        try:
            # Run the supplied runtime operation outside the FastAPI event loop.
            # Some runtime layers perform local model calls, filesystem work,
            # sandbox validation, installs, or other blocking operations.  If
            # those operations run directly inside the server loop, other pages
            # such as Runtime State Console cannot load until the job ends.
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(job_id))
            timeout_seconds = self._timeout_from_record(record)
            worker_future = asyncio.to_thread(self._run_runner_in_private_loop, runner)
            if timeout_seconds > 0:
                result = await asyncio.wait_for(worker_future, timeout=timeout_seconds)
            else:
                result = await worker_future
            record["result"] = result if isinstance(result, dict) else {"value": result}
            result_status = str((record["result"] or {}).get("status") or "completed")
            waiting_statuses = {"requires_input", "requires_key", "waiting_input", "paused", "blocked_waiting_input", "requires_human_confirmation"}
            if result_status in {"failed", "error"}:
                record["status"] = "failed"
            elif result_status in waiting_statuses:
                record["status"] = "paused"
            else:
                record["status"] = "completed"
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
            timeout_type = isinstance(exc, asyncio.TimeoutError)
            timeout_seconds = self._timeout_from_record(record)
            message = (
                f"Async runtime job exceeded timeout_seconds={timeout_seconds}. The durable job was marked failed so the UI can recover."
                if timeout_type
                else str(exc)
            )
            record["status"] = "failed"
            record["error"] = {"type": "AsyncJobTimeout" if timeout_type else exc.__class__.__name__, "message": message, "timeout_seconds": timeout_seconds if timeout_type else None}
            record["result"] = {
                "ok": False,
                "status": "failed",
                "final_answer": message,
                "error": record["error"],
                "runtime_state": {"run_id": job_id, "state_url": f"/runtime-state?run_id={job_id}"},
            }
            record["finished_at"] = self._now()
            record["updated_at"] = record["finished_at"]
            runtime_state_manager.emit(
                run_id=job_id,
                step_id="job.error",
                level="developer",
                kind="error",
                status="failed",
                title="Job failed",
                message=message,
                error=record["error"],
                progress=100,
            )
            runtime_state_manager.finish_run(job_id, status="failed", summary=message, error=record["error"], output={"timeout_seconds": timeout_seconds} if timeout_type else None)
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(BaseException):
                    await heartbeat_task
        self._write(record)

    async def _heartbeat_loop(self, job_id: str) -> None:
        """Keep the async job watchdog alive while a private worker is busy.

        Long local-model, graph, web, sandbox, or generated-tool operations may
        be legitimately quiet for many minutes on small local machines.  The
        worker-owned heartbeat is generic lifecycle metadata; it does not mark a
        step as successful and it does not hide terminal failures from the
        runner.
        """
        interval = self._resolve_heartbeat_interval_seconds(job_id=job_id)
        while True:
            await asyncio.sleep(interval)
            record = self._jobs.get(job_id) or self._read(job_id)
            if not isinstance(record, dict) or str(record.get("status") or "") not in {"queued", "running"}:
                return
            now = self._now()
            watchdog = record.get("watchdog") if isinstance(record.get("watchdog"), dict) else {}
            watchdog = dict(watchdog)
            watchdog["last_heartbeat_at"] = now
            record["watchdog"] = watchdog
            record["updated_at"] = now
            self._jobs[job_id] = record
            self._write(record)
            try:
                runtime_state_manager.emit(
                    run_id=job_id,
                    step_id="job.heartbeat",
                    level="developer",
                    kind="lifecycle",
                    status="running",
                    title="Job heartbeat",
                    message="Async worker is still running; watchdog heartbeat refreshed.",
                    method="async_worker",
                    progress=None,
                    output={
                        "heartbeat_at": now,
                        "job_family": (record.get("metadata") or {}).get("job_family") if isinstance(record.get("metadata"), dict) else None,
                    },
                )
            except Exception:
                pass

    def _resolve_heartbeat_interval_seconds(self, *, job_id: str | None = None, metadata: dict[str, Any] | None = None) -> int:
        meta = metadata if isinstance(metadata, dict) else {}
        if job_id:
            record = self._jobs.get(job_id) or self._read(job_id)
            if isinstance(record, dict) and isinstance(record.get("metadata"), dict):
                meta = record.get("metadata") or {}
        for key in ("heartbeat_interval_seconds", "watchdog_heartbeat_interval_seconds"):
            if key in meta:
                try:
                    return max(5, int(meta.get(key) or 0))
                except Exception:
                    continue
        try:
            settings = self.lifecycle_settings_store.load()
            return max(5, int(settings.heartbeat_interval_seconds))
        except Exception:
            try:
                return max(5, int(os.getenv("AI_RUNTIME_ASYNC_JOB_HEARTBEAT_SECONDS") or "30"))
            except Exception:
                return 30

    def _run_runner_in_private_loop(self, runner: Callable[[], Awaitable[dict[str, Any]]]) -> Any:
        value = runner()
        if inspect.isawaitable(value):
            return asyncio.run(value)
        return value

    def _resolve_timeout_seconds(self, *, timeout_seconds: int | None = None, metadata: dict[str, Any] | None = None) -> int:
        if timeout_seconds is not None:
            try:
                return max(0, int(timeout_seconds))
            except Exception:
                pass
        meta = metadata if isinstance(metadata, dict) else {}
        for key in ("timeout_seconds", "max_runtime_seconds", "job_timeout_seconds"):
            if key in meta:
                try:
                    return max(0, int(meta.get(key) or 0))
                except Exception:
                    continue
        family = str(meta.get("job_family") or "task_execution").strip() or "task_execution"
        try:
            return int(self.lifecycle_settings_store.policy_for_family(family).get("timeout_seconds") or 3600)
        except Exception:
            try:
                return max(0, int(os.getenv("AI_RUNTIME_ASYNC_JOB_TIMEOUT_SECONDS") or "3600"))
            except Exception:
                return 3600

    def _resolve_stale_seconds(self, *, metadata: dict[str, Any] | None = None) -> int:
        meta = metadata if isinstance(metadata, dict) else {}
        for key in ("stale_after_seconds", "watchdog_stale_seconds"):
            if key in meta:
                try:
                    return max(30, int(meta.get(key) or 0))
                except Exception:
                    continue
        family = str(meta.get("job_family") or "task_execution").strip() or "task_execution"
        try:
            return int(self.lifecycle_settings_store.policy_for_family(family).get("stale_after_seconds") or 1200)
        except Exception:
            try:
                return max(30, int(os.getenv("AI_RUNTIME_ASYNC_JOB_STALE_SECONDS") or "1200"))
            except Exception:
                return 1200

    def _timeout_from_record(self, record: dict[str, Any]) -> int:
        try:
            return max(0, int(record.get("timeout_seconds") or 0))
        except Exception:
            return 0

    def _parse_ts(self, value: Any) -> datetime | None:
        try:
            text = str(value or "")
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def _stale_watchdog_enabled(self, record: dict[str, Any]) -> bool:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        if metadata.get("stale_watchdog_enabled") is False:
            return False
        if str(metadata.get("job_family") or "").strip() == "capability_acquisition":
            return False
        watchdog = record.get("watchdog") if isinstance(record.get("watchdog"), dict) else {}
        if watchdog.get("enabled") is False:
            return False
        return True

    def _recover_stale_running_job(self, record: dict[str, Any]) -> dict[str, Any]:
        status = str(record.get("status") or "")
        if status not in {"queued", "running"}:
            return record
        job_id = str(record.get("job_id") or "")
        if not job_id:
            return record
        timeout_seconds = self._timeout_from_record(record)
        started_at = self._parse_ts(record.get("started_at") or record.get("created_at"))
        watchdog = record.get("watchdog") if isinstance(record.get("watchdog"), dict) else {}
        stale_after_seconds = self._resolve_stale_seconds(metadata={"stale_after_seconds": watchdog.get("stale_after_seconds")})
        heartbeat_at = self._parse_ts(watchdog.get("last_heartbeat_at"))
        updated_at = self._parse_ts(record.get("updated_at"))
        last_activity_at = max([dt for dt in [heartbeat_at, updated_at, started_at] if dt is not None], default=None)
        now_dt = datetime.now(timezone.utc)
        timed_out = bool(timeout_seconds > 0 and started_at and (now_dt - started_at).total_seconds() > timeout_seconds)
        stale = bool(
            self._stale_watchdog_enabled(record)
            and last_activity_at
            and (now_dt - last_activity_at).total_seconds() > stale_after_seconds
        )
        if not timed_out and not stale:
            return record
        if timed_out:
            message = f"Async runtime job exceeded timeout_seconds={timeout_seconds} without a terminal result. The durable job was recovered as failed."
            error_type = "AsyncJobWatchdogTimeout"
        else:
            message = f"Async runtime job produced no progress for stale_after_seconds={stale_after_seconds}. The durable job was recovered as failed with a visible result."
            error_type = "AsyncJobStaleNoProgress"
        recovered = dict(record)
        recovered["status"] = "failed"
        recovered["updated_at"] = self._now()
        recovered["finished_at"] = recovered.get("finished_at") or recovered["updated_at"]
        recovered["error"] = {"type": error_type, "message": message, "timeout_seconds": timeout_seconds, "stale_after_seconds": stale_after_seconds}
        recovered["result"] = {
            "ok": False,
            "status": "failed",
            "final_answer": message,
            "error": recovered["error"],
            "runtime_state": {"run_id": job_id, "state_url": f"/runtime-state?run_id={job_id}"},
            "durable_recovered": True,
        }
        self._jobs[job_id] = recovered
        self._write(recovered)
        try:
            runtime_state_manager.finish_run(job_id, status="failed", summary=message, error=recovered["error"], output={"watchdog": recovered["error"].get("type")})
        except Exception:
            pass
        return recovered


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
            job_id = str(record.get("job_id") or path.stem)
            recovered = self._merge_durable_runtime_state({**record, "job_id": job_id})
            if str(recovered.get("status") or "") in {"completed", "paused", "failed", "cancelled"}:
                self._jobs[job_id] = recovered
                self._write(recovered)
                continue
            record["status"] = "interrupted"
            record["updated_at"] = now
            record["finished_at"] = record.get("finished_at") or now
            record["error"] = {"type": "RuntimeRestart", "message": reason}
            self._jobs[job_id] = record
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

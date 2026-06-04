from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable


class ScheduledTaskRunner:
    """Generic durable task scheduler.

    It scans task graph records for a user-declared execution policy and asks
    the provided executor to run due task graphs. It does not know what any task,
    agent, or capability does.
    """

    def __init__(self, *, tasks_dir: Path | str = Path("runtime") / "generated" / "tasks", trace_dir: Path | str = Path("runtime") / "traces" / "scheduled_tasks") -> None:
        self.tasks_dir = Path(tasks_dir)
        self.trace_dir = Path(trace_dir)
        self._task: asyncio.Task[Any] | None = None
        self._stopped = asyncio.Event()

    def start(self, executor: Callable[..., Awaitable[dict[str, Any]]], *, tick_seconds: int = 5) -> None:
        if self._task and not self._task.done():
            return
        self._stopped = asyncio.Event()
        self._task = asyncio.create_task(self._loop(executor, max(1, int(tick_seconds))))

    async def stop(self) -> None:
        self._stopped.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self, executor: Callable[..., Awaitable[dict[str, Any]]], tick_seconds: int) -> None:
        while not self._stopped.is_set():
            try:
                await self.run_once(executor)
            except Exception as exc:
                self._trace({"event": "scheduler_loop_error", "error_type": exc.__class__.__name__, "error": str(exc)})
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=tick_seconds)
            except asyncio.TimeoutError:
                pass

    async def run_once(self, executor: Callable[..., Awaitable[dict[str, Any]]]) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        executed: list[dict[str, Any]] = []
        for path in sorted(self.tasks_dir.glob("*.json")):
            task_graph = self._read(path)
            if not isinstance(task_graph, dict):
                continue
            policy = task_graph.get("schedule_policy") if isinstance(task_graph.get("schedule_policy"), dict) else {}
            if not bool(policy.get("enabled")):
                continue
            if str(policy.get("mode") or "") != "recurring":
                continue
            next_run_at = self._parse_time(policy.get("next_run_at")) or now
            if next_run_at > now:
                continue
            task_name = str(task_graph.get("task_name") or path.stem)
            self._trace({"event": "scheduled_task_due", "task_name": task_name, "next_run_at": next_run_at.isoformat()})
            try:
                controller_ids = self._controller_participant_ids(task_graph)
                payload_ids = self._payload_participant_ids(task_graph, controller_ids)
                self._trace({
                    "event": "payload_dispatch_started",
                    "task_name": task_name,
                    "skipped_controller_participants": controller_ids,
                    "payload_participants": payload_ids,
                })
                result = await executor(task_name, task_graph)
                executed.append({"task_name": task_name, "status": result.get("status"), "run_id": result.get("run_id")})
                self._trace({
                    "event": "payload_dispatch_completed",
                    "task_name": task_name,
                    "result_status": result.get("status"),
                    "run_id": result.get("run_id"),
                    "missing_inputs": result.get("missing_inputs") or [],
                    "pending_action_kind": ((result.get("pending_action") or {}).get("kind") if isinstance(result.get("pending_action"), dict) else None),
                })
                self._trace({"event": "scheduled_task_executed", "task_name": task_name, "result_status": result.get("status"), "run_id": result.get("run_id")})
            except Exception as exc:
                executed.append({"task_name": task_name, "status": "failed", "error": str(exc)})
                self._trace({"event": "scheduled_task_execute_failed", "task_name": task_name, "error_type": exc.__class__.__name__, "error": str(exc)})
            interval = int(policy.get("interval_seconds") or 0)
            if interval > 0:
                policy["last_run_at"] = now.isoformat()
                policy["next_run_at"] = (now + timedelta(seconds=interval)).isoformat()
                task_graph["schedule_policy"] = policy
                self._write(path, task_graph)
        return executed

    def _controller_participant_ids(self, task_graph: dict[str, Any]) -> list[str]:
        policy = task_graph.get("schedule_policy") if isinstance(task_graph.get("schedule_policy"), dict) else {}
        return [str(x).strip() for x in (policy.get("controller_participant_ids") or []) if str(x).strip()]

    def _payload_participant_ids(self, task_graph: dict[str, Any], controller_ids: list[str]) -> list[str]:
        selected = [str(x).strip() for x in (task_graph.get("selected_participant_ids") or []) if str(x).strip()]
        controllers = set(controller_ids)
        payload = [x for x in selected if x not in controllers]
        if payload:
            return payload
        tasks = task_graph.get("tasks") if isinstance(task_graph.get("tasks"), list) else []
        derived: list[str] = []
        for item in tasks:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("participant_id") or "").strip()
            if pid and pid not in controllers:
                derived.append(pid)
        return derived

    def _read(self, path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _parse_time(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            text = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _trace(self, payload: dict[str, Any]) -> None:
        try:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **payload}
            with (self.trace_dir / "scheduler.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            return

from __future__ import annotations

import asyncio
import copy
import inspect
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
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._worker_sequence = 0

    def start(self, executor: Callable[..., Awaitable[dict[str, Any]]], *, tick_seconds: int = 5) -> bool:
        """Start the background loop when an event loop is available.

        Returning a boolean makes startup observable without forcing callers to
        special-case synchronous contexts.  The scheduler is generic runtime
        infrastructure and remains idle until it sees task graphs with enabled
        schedule policies.
        """
        if self._task and not self._task.done():
            return True
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self._trace({"event": "scheduler_start_deferred", "reason": "no_running_event_loop"})
            return False
        self._stopped = asyncio.Event()
        self._task = asyncio.create_task(self._loop(executor, max(1, int(tick_seconds))))
        self._trace({"event": "scheduler_started", "tick_seconds": max(1, int(tick_seconds))})
        return True

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
        self._prune_inflight()
        for path in self._task_record_paths():
            task_graph = self._read(path)
            if not isinstance(task_graph, dict):
                continue
            policy = task_graph.get("schedule_policy") if isinstance(task_graph.get("schedule_policy"), dict) else {}
            if not bool(policy.get("enabled")):
                continue
            if str(policy.get("state") or "active").strip().casefold() not in {"active", "running", "resumed"}:
                continue
            mode = str(policy.get("mode") or "").strip().casefold()
            if mode not in {"recurring", "once", "one_time", "one-time"}:
                continue
            next_run_at = self._parse_time(policy.get("next_run_at")) or now
            if next_run_at > now:
                continue
            task_name = str(task_graph.get("task_name") or (path.parent.name if path.name == "source_task_graph.json" else path.stem))
            schedule_instance_id = str(policy.get("schedule_instance_id") or task_graph.get("schedule_instance_id") or f"schedule_{task_name}")
            policy.setdefault("schedule_instance_id", schedule_instance_id)
            policy.setdefault("lifecycle_key", schedule_instance_id)
            interval = int(policy.get("interval_seconds") or 0)

            if schedule_instance_id in self._inflight:
                if interval > 0:
                    policy["last_skip_at"] = now.isoformat()
                    policy["next_run_at"] = (now + timedelta(seconds=interval)).isoformat()
                    task_graph["schedule_policy"] = policy
                    self._write(path, task_graph)
                self._trace({
                    "event": "scheduled_task_overlap_skipped",
                    "task_name": task_name,
                    "schedule_instance_id": schedule_instance_id,
                    "next_run_at": policy.get("next_run_at"),
                    "reason": "same_schedule_instance_already_running",
                })
                executed.append({"task_name": task_name, "status": "skipped_running", "schedule_instance_id": schedule_instance_id})
                continue

            self._trace({"event": "due_task_found", "task_name": task_name, "schedule_instance_id": schedule_instance_id, "next_run_at": next_run_at.isoformat()})
            self._trace({"event": "scheduled_task_due", "task_name": task_name, "schedule_instance_id": schedule_instance_id, "next_run_at": next_run_at.isoformat()})

            if interval > 0 and mode == "recurring":
                policy["last_dispatched_at"] = now.isoformat()
                policy["next_run_at"] = (now + timedelta(seconds=interval)).isoformat()
            else:
                policy["last_dispatched_at"] = now.isoformat()
                policy["enabled"] = False
                policy["state"] = "completed"
            task_graph["schedule_policy"] = policy
            self._write(path, task_graph)
            self._trace({
                "event": "next_run_at_updated",
                "task_name": task_name,
                "schedule_instance_id": schedule_instance_id,
                "next_run_at": policy.get("next_run_at"),
                "last_run_at": policy.get("last_dispatched_at"),
                "update_timing": "before_dispatch",
            })

            try:
                controller_ids = self._controller_participant_ids(task_graph)
                payload_ids = self._payload_participant_ids(task_graph, controller_ids)
                self._trace({
                    "event": "dispatch_started",
                    "task_name": task_name,
                    "skipped_controller_participants": controller_ids,
                    "payload_participants": payload_ids,
                    "schedule_instance_id": schedule_instance_id,
                })
                worker_id = self._next_worker_id(schedule_instance_id)
                dispatch_task = asyncio.create_task(
                    self._dispatch_and_trace(executor, task_name, task_graph, schedule_instance_id, worker_id)
                )
                self._inflight[schedule_instance_id] = dispatch_task
                self._trace({
                    "event": "isolated_worker_dispatched",
                    "task_name": task_name,
                    "schedule_instance_id": schedule_instance_id,
                    "worker_id": worker_id,
                    "isolation": "private_thread_private_event_loop",
                })
                executed.append({"task_name": task_name, "status": "dispatched", "schedule_instance_id": schedule_instance_id, "worker_id": worker_id})
            except Exception as exc:
                executed.append({"task_name": task_name, "status": "failed", "error": str(exc)})
                self._trace({"event": "scheduled_task_dispatch_failed", "task_name": task_name, "error_type": exc.__class__.__name__, "error": str(exc)})
        return executed

    async def _dispatch_and_trace(
        self,
        executor: Callable[..., Awaitable[dict[str, Any]]],
        task_name: str,
        task_graph: dict[str, Any],
        schedule_instance_id: str,
        worker_id: str,
    ) -> None:
        try:
            worker_graph = copy.deepcopy(task_graph)
            worker_policy = worker_graph.get("schedule_policy") if isinstance(worker_graph.get("schedule_policy"), dict) else {}
            worker_policy["schedule_instance_id"] = schedule_instance_id
            worker_policy["worker_id"] = worker_id
            worker_policy["execution_isolation"] = "private_thread_private_event_loop"
            worker_graph["schedule_policy"] = worker_policy
            worker_graph["scheduled_execution_scope"] = {
                "task_name": task_name,
                "schedule_instance_id": schedule_instance_id,
                "worker_id": worker_id,
                "isolation": "private_thread_private_event_loop",
            }
            self._trace({
                "event": "isolated_worker_started",
                "task_name": task_name,
                "schedule_instance_id": schedule_instance_id,
                "worker_id": worker_id,
            })
            result = await asyncio.to_thread(self._call_executor_in_private_loop, executor, task_name, worker_graph)
            if not isinstance(result, dict):
                result = {"status": "completed", "result": result}
            self._trace({
                "event": "dispatch_completed",
                "task_name": task_name,
                "result_status": result.get("status"),
                "run_id": result.get("run_id"),
                "schedule_instance_id": schedule_instance_id,
                "worker_id": worker_id,
                "missing_inputs": result.get("missing_inputs") or [],
                "pending_action_kind": ((result.get("pending_action") or {}).get("kind") if isinstance(result.get("pending_action"), dict) else None),
            })
            self._trace({"event": "scheduled_task_executed", "task_name": task_name, "schedule_instance_id": schedule_instance_id, "worker_id": worker_id, "result_status": result.get("status"), "run_id": result.get("run_id")})
        except Exception as exc:
            self._trace({"event": "scheduled_task_execute_failed", "task_name": task_name, "schedule_instance_id": schedule_instance_id, "worker_id": worker_id, "error_type": exc.__class__.__name__, "error": str(exc)})
        finally:
            self._inflight.pop(schedule_instance_id, None)

    def _prune_inflight(self) -> None:
        for key, task in list(self._inflight.items()):
            if task.done():
                self._inflight.pop(key, None)

    def _task_record_paths(self) -> list[Path]:
        compiled_sources = list(self.tasks_dir.glob("*/source_task_graph.json"))
        compiled_ids = {path.parent.name for path in compiled_sources}
        legacy = [path for path in self.tasks_dir.glob("*.json") if path.stem not in compiled_ids]
        return sorted(legacy + compiled_sources)


    def _next_worker_id(self, schedule_instance_id: str) -> str:
        self._worker_sequence += 1
        safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(schedule_instance_id or "schedule"))[:80]
        return f"worker_{safe}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{self._worker_sequence}"

    def _call_executor_in_private_loop(self, executor: Callable[..., Awaitable[dict[str, Any]]], task_name: str, task_graph: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self._call_executor(executor, task_name, task_graph))

    async def _call_executor(self, executor: Callable[..., Awaitable[dict[str, Any]]], task_name: str, task_graph: dict[str, Any]) -> dict[str, Any]:
        """Call either legacy one-argument or graph-aware executors."""
        try:
            signature = inspect.signature(executor)
            positional = [
                p for p in signature.parameters.values()
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                and p.default is p.empty
            ]
            accepts_varargs = any(p.kind == p.VAR_POSITIONAL for p in signature.parameters.values())
            if accepts_varargs or len(positional) >= 2:
                return await executor(task_name, task_graph)
            return await executor(task_name)
        except (TypeError, ValueError):
            try:
                return await executor(task_name, task_graph)
            except TypeError:
                return await executor(task_name)

    def _controller_participant_ids(self, task_graph: dict[str, Any]) -> list[str]:
        policy = task_graph.get("schedule_policy") if isinstance(task_graph.get("schedule_policy"), dict) else {}
        return [str(x).strip() for x in (policy.get("controller_participant_ids") or []) if str(x).strip()]

    def _payload_participant_ids(self, task_graph: dict[str, Any], controller_ids: list[str]) -> list[str]:
        """Return payload participant ids from the executable task list first.

        Scheduled graphs may keep a stale selected_participant_ids list from the
        semantic planning phase.  The durable tasks array is the compiled
        executable graph, so it must be the source of truth for dispatch.
        This keeps each scheduled task isolated and prevents a shared timing
        controller or stale participant selection from dropping generated
        payload steps.
        """
        controllers = set(controller_ids)
        tasks = task_graph.get("tasks") if isinstance(task_graph.get("tasks"), list) else []
        derived: list[str] = []
        for item in tasks:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("participant_id") or "").strip()
            if pid and pid not in controllers and pid not in derived:
                derived.append(pid)
        if derived:
            return derived
        selected = [str(x).strip() for x in (task_graph.get("selected_participant_ids") or []) if str(x).strip()]
        return [x for x in selected if x not in controllers]

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
            event_payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **payload}
            with (self.trace_dir / "scheduler.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event_payload, ensure_ascii=False) + "\n")
            lifecycle_dir = Path("runtime") / "traces" / "service_lifecycle"
            lifecycle_dir.mkdir(parents=True, exist_ok=True)
            with (lifecycle_dir / "scheduled_task_runner.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event_payload, ensure_ascii=False) + "\n")
            try:
                from auxiliary_brain.runtime.observability.runtime_console import emit_console_event
                event_name = str(payload.get("event") or "scheduler_event")
                if event_name != "scheduler_tick":
                    emit_console_event(
                        area="scheduler",
                        event=event_name,
                        status="info",
                        message=event_name,
                        data={k: v for k, v in payload.items() if k != "event"},
                    )
            except Exception:
                pass
        except Exception:
            return

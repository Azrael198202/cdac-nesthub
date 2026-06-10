from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterable

from ai_core.config.paths import RUNTIME_TRACES
from auxiliary_brain.runtime.observability.runtime_console import emit_console_event
from .contracts import RuntimeRunState, RuntimeStateEvent, RuntimeStepState, default_runtime_flow, resolve_flow_id, utc_now


class RuntimeStateManager:
    """Generic end-to-end runtime state manager.

    The manager records lifecycle, IO, method/tool usage, progress, API calls,
    downloads, installs, command execution, validation, verification, and repair
    events. It is observability/state infrastructure only and does not make
    business, capability, provider, or workflow decisions.
    """

    def __init__(self, *, state_dir: Path | str | None = None, recent_limit: int = 500) -> None:
        self.state_dir = Path(state_dir) if state_dir else RUNTIME_TRACES / "runtime_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.recent_limit = max(50, int(recent_limit or 500))
        self._lock = threading.RLock()
        self._runs: dict[str, RuntimeRunState] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._sequence: dict[str, int] = {}

    def start_run(self, run_id: str, *, task_id: str = "", title: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        run_id = self._safe_id(run_id or "runtime")
        with self._lock:
            run = self._runs.get(run_id) or self._read_run(run_id) or RuntimeRunState(run_id=run_id)
            run.task_id = task_id or run.task_id
            run.title = title or run.title or run_id
            run.status = "running"
            run.started_at = run.started_at or utc_now()
            run.updated_at = utc_now()
            if isinstance(metadata, dict):
                run.metadata.update(self._redact_data(metadata))
            if not run.flow:
                run.flow = default_runtime_flow()
            self._runs[run_id] = run
            self._write_run(run)
        self.emit(run_id=run_id, step_id="run.lifecycle", kind="lifecycle", level="developer", status="running", title="Run started", message=run.title, progress=0, metadata=metadata or {})
        return run.to_dict()

    def finish_run(self, run_id: str, *, status: str = "completed", summary: str = "", output: Any | None = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
        run_id = self._safe_id(run_id or "runtime")
        with self._lock:
            run = self._runs.get(run_id) or self._read_run(run_id) or RuntimeRunState(run_id=run_id)
            run.status = "failed" if status in {"failed", "error"} else status or "completed"
            run.ended_at = utc_now()
            run.updated_at = run.ended_at
            run.progress = 100.0 if run.status == "completed" else run.progress
            run.summary = str(summary or run.summary or "")[-4000:]
            if error:
                run.last_error = self._redact_data(error)
            self._runs[run_id] = run
            self._write_run(run)
        self.emit(
            run_id=run_id,
            step_id="run.lifecycle",
            kind="output" if run.status in {"completed", "paused"} else "error",
            level="user" if run.status in {"completed", "paused"} else "developer",
            status=run.status,
            title="Run finished",
            message=summary or run.status,
            output=output,
            error=error,
            progress=100.0 if run.status in {"completed", "paused"} else None,
        )
        with self._lock:
            final = self._runs.get(run_id) or self._read_run(run_id) or run
            self._force_terminal_state(final, status=run.status, summary=summary, error=error)
            self._runs[run_id] = final
            self._write_run(final)
            return final.to_dict()

    def emit(
        self,
        *,
        run_id: str,
        step_id: str = "runtime",
        task_id: str = "",
        parent_step_id: str = "",
        level: str = "developer",
        kind: str = "lifecycle",
        status: str = "running",
        title: str = "",
        message: str = "",
        input: Any | None = None,
        output: Any | None = None,
        method: str = "",
        tool: str = "",
        progress: float | None = None,
        error: dict[str, Any] | None = None,
        trace: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        next_action: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = self._safe_id(run_id or "runtime")
        step_id = self._safe_step_id(step_id or "runtime")
        now = utc_now()
        terminal_statuses_for_event = {"completed", "failed", "skipped", "cancelled", "interrupted"}
        effective_progress = progress
        if str(status or "") in terminal_statuses_for_event:
            effective_progress = 100.0
        with self._lock:
            run = self._runs.get(run_id) or self._read_run(run_id) or RuntimeRunState(run_id=run_id, title=run_id)
            seq = self._sequence.get(run_id, int(run.event_count or 0)) + 1
            self._sequence[run_id] = seq
            flow_id = resolve_flow_id(step_id, kind=kind, method=method)
            event = RuntimeStateEvent(
                run_id=run_id,
                task_id=task_id or run.task_id,
                step_id=step_id,
                flow_id=flow_id,
                parent_step_id=parent_step_id,
                sequence=seq,
                level=level,
                kind=kind,
                status=status,
                title=title or step_id,
                message=str(message or "")[-4000:],
                input=self._redact_data(input),
                output=self._redact_data(output),
                method=method,
                tool=tool,
                progress=effective_progress,
                started_at=now if status in {"running", "planning", "generating", "validating", "verifying", "repairing"} else None,
                ended_at=now if status in {"completed", "failed", "skipped", "cancelled"} else None,
                error=self._redact_data(error) if error else None,
                trace=self._redact_data(trace or {}),
                evidence=self._redact_data(evidence or []),
                next_action=next_action,
                metadata=self._redact_data(metadata or {}),
            ).to_dict()
            step = run.steps.get(step_id) or RuntimeStepState(step_id=step_id, flow_id=flow_id, name=title or step_id)
            step.flow_id = flow_id or step.flow_id
            step.name = title or step.name or step_id
            step.status = status or step.status
            step.level = level or step.level
            step.kind = kind or step.kind
            if input is not None:
                step.input = self._redact_data(input)
            if output is not None:
                step.output = self._redact_data(output)
            if method:
                step.method = method
            if tool:
                step.tool = tool
            if effective_progress is not None:
                try:
                    step.progress = max(0.0, min(100.0, float(effective_progress)))
                except Exception:
                    pass
            if status in {"running", "planning", "generating", "validating", "verifying", "repairing"}:
                step.started_at = step.started_at or now
            if status in {"completed", "failed", "skipped", "cancelled"}:
                step.ended_at = now
                step.progress = 100.0
            if error:
                step.error = self._redact_data(error)
                run.last_error = step.error
            if trace:
                step.trace.update(self._redact_data(trace))
            if evidence:
                step.evidence.extend(self._redact_data(evidence))
                step.evidence = step.evidence[-20:]
            if next_action:
                step.next_action = next_action
            step.last_message = str(message or title or "")[-2000:]
            step.event_count += 1
            run.steps[step_id] = step
            self._update_flow_from_step(run, step)
            active_statuses = {"created", "queued", "waiting_input", "planning", "generating", "validating", "running", "verifying", "repairing", "paused"}
            terminal_statuses = {"completed", "failed", "skipped", "cancelled", "interrupted"}
            if status == "failed":
                run.status = "failed"
            elif status in active_statuses:
                run.status = status if status not in {"created"} else "running"
                run.active_step_id = step_id
            elif status in terminal_statuses:
                if run.active_step_id == step_id:
                    run.active_step_id = self._find_active_step_id(run)
            run.updated_at = now
            run.event_count = seq
            run.last_event_id = str(event.get("event_id") or "")
            self._recalculate_run_progress(run)
            self._runs[run_id] = run
            self._append_event(run_id, event)
            self._write_run(run)
        emit_console_event(
            area="runtime_state",
            event=str(event.get("kind") or "event"),
            status=str(event.get("status") or "running"),
            message=str(event.get("message") or event.get("title") or ""),
            data={k: v for k, v in event.items() if k not in {"input", "output"}},
        )
        return event

    def _force_terminal_state(self, run: RuntimeRunState, *, status: str, summary: str = "", error: dict[str, Any] | None = None) -> None:
        terminal_status = "failed" if status in {"failed", "error"} else str(status or "completed")
        if terminal_status not in {"completed", "failed", "cancelled", "paused", "interrupted"}:
            terminal_status = "completed"
        now = utc_now()
        run.status = terminal_status
        run.ended_at = run.ended_at or now
        run.updated_at = now
        run.summary = str(summary or run.summary or terminal_status)[-4000:]
        if error:
            run.last_error = self._redact_data(error)
        active_statuses = {"created", "queued", "waiting_input", "planning", "generating", "validating", "running", "verifying", "repairing", "paused"}
        for step in run.steps.values():
            if step.status in active_statuses:
                if step.step_id in {"run.lifecycle", "job.result", "job.run", "job.queue"}:
                    step.status = terminal_status if terminal_status != "paused" else "paused"
                else:
                    step.status = "skipped" if terminal_status == "completed" else terminal_status
                step.progress = 100.0 if terminal_status in {"completed", "skipped"} else max(float(step.progress or 0.0), 100.0 if terminal_status == "failed" else float(step.progress or 0.0))
                step.ended_at = step.ended_at or now
        used_flow_ids = {step.flow_id for step in run.steps.values() if step.flow_id}
        for node in run.flow or []:
            node_status = str(node.get("status") or "created")
            if terminal_status == "completed":
                if node_status in {"created", "pending", "not_started", "queued", "waiting_input", "planning", "generating", "validating", "running", "verifying", "repairing", "paused"}:
                    if node.get("flow_id") in used_flow_ids:
                        node["status"] = "completed"
                        node["last_message"] = node.get("last_message") or "Flow completed by the selected execution path."
                    else:
                        node["status"] = "skipped"
                        node["last_message"] = "This flow node was not used by the selected execution path."
                    node["progress"] = 100.0
            elif terminal_status in {"failed", "interrupted"} and node_status in {"running", "queued", "waiting_input", "planning", "generating", "validating", "verifying", "repairing"}:
                node["status"] = "failed"
                node["progress"] = 100.0
            node["active"] = False
            node["updated_at"] = now
        run.active_step_id = ""
        if terminal_status == "completed":
            run.progress = 100.0


    def close_non_terminal_runs_on_startup(self, *, reason: str = "Runtime process restarted before the previous worker finished.") -> int:
        """Mark durable runs left active by a server reload/restart as interrupted.

        This is observability cleanup only. It does not retry or alter the
        workflow plan. It prevents the UI from showing stale `running` states
        after WatchFiles or a manual server restart kills the in-process worker.
        """
        active_statuses = {"created", "queued", "waiting_input", "planning", "generating", "validating", "running", "verifying", "repairing"}
        count = 0
        with self._lock:
            try:
                paths = list(self.state_dir.glob("*/run_state.json"))
            except Exception:
                paths = []
            for path in paths:
                run_id = path.parent.name
                run = self._read_run(run_id)
                if not run or str(run.status or "") not in active_statuses:
                    continue
                self._force_terminal_state(run, status="interrupted", summary=reason, error={"type": "RuntimeRestart", "message": reason})
                self._runs[run_id] = run
                self._write_run(run)
                count += 1
        return count

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run_id = self._safe_id(run_id)
        with self._lock:
            run = self._runs.get(run_id) or self._read_run(run_id)
            if not run:
                return None
            self._runs[run_id] = run
            return run.to_dict()

    def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._runs.values())
            try:
                for path in self.state_dir.glob("*/run_state.json"):
                    run_id = path.parent.name
                    if run_id not in self._runs:
                        run = self._read_run(run_id)
                        if run:
                            items.append(run)
            except Exception:
                pass
            unique: dict[str, RuntimeRunState] = {item.run_id: item for item in items}
            out = sorted(unique.values(), key=lambda x: str(x.updated_at or x.created_at or ""), reverse=True)
            return [x.to_dict() for x in out[: max(1, int(limit or 50))]]

    def list_events(self, run_id: str, *, after_sequence: int = 0, limit: int = 300, min_level: str | None = None) -> list[dict[str, Any]]:
        run_id = self._safe_id(run_id)
        events = self._events.get(run_id)
        if events is None:
            events = self._read_events(run_id)
            self._events[run_id] = events[-self.recent_limit:]
        levels = ["user", "developer", "advanced", "diagnostic"]
        min_index = 0
        if min_level in levels:
            min_index = levels.index(str(min_level))
        filtered = []
        for item in events:
            try:
                if int(item.get("sequence") or 0) <= int(after_sequence or 0):
                    continue
            except Exception:
                continue
            level = str(item.get("level") or "developer")
            if min_level in levels and level in levels and levels.index(level) < min_index:
                continue
            filtered.append(item)
        return filtered[: max(1, min(int(limit or 300), 1000))]

    def _append_event(self, run_id: str, event: dict[str, Any]) -> None:
        path = self._run_dir(run_id) / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        events = self._events.setdefault(run_id, [])
        events.append(event)
        if len(events) > self.recent_limit:
            del events[: len(events) - self.recent_limit]

    def _write_run(self, run: RuntimeRunState) -> None:
        path = self._run_dir(run.run_id) / "run_state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_run(self, run_id: str) -> RuntimeRunState | None:
        path = self._run_dir(run_id) / "run_state.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        run = RuntimeRunState(run_id=str(data.get("run_id") or run_id))
        for key in ("task_id", "status", "title", "created_at", "updated_at", "started_at", "ended_at", "progress", "active_step_id", "summary", "metadata", "flow", "event_count", "last_event_id", "last_error"):
            if key in data:
                setattr(run, key, data.get(key))
        steps = data.get("steps") if isinstance(data.get("steps"), list) else []
        for item in steps:
            if not isinstance(item, dict) or not item.get("step_id"):
                continue
            step = RuntimeStepState(step_id=str(item.get("step_id")))
            for k, v in item.items():
                if hasattr(step, k):
                    setattr(step, k, v)
            if not getattr(step, "flow_id", ""):
                step.flow_id = resolve_flow_id(step.step_id, kind=getattr(step, "kind", ""), method=getattr(step, "method", ""))
            run.steps[step.step_id] = step
        if not run.flow:
            run.flow = default_runtime_flow()
        for step in run.steps.values():
            self._update_flow_from_step(run, step, persist_event=False)
        return run

    def _read_events(self, run_id: str) -> list[dict[str, Any]]:
        path = self._run_dir(run_id) / "events.jsonl"
        out: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        out.append(item)
                except Exception:
                    continue
        except Exception:
            pass
        return out

    def _run_dir(self, run_id: str) -> Path:
        return self.state_dir / self._safe_id(run_id)

    def _update_flow_from_step(self, run: RuntimeRunState, step: RuntimeStepState, *, persist_event: bool = True) -> None:
        if not run.flow:
            run.flow = default_runtime_flow()
        target = step.flow_id or resolve_flow_id(step.step_id, kind=step.kind, method=step.method)
        for node in run.flow:
            if node.get("flow_id") != target:
                continue
            previous_status = str(node.get("status") or "")
            terminal = {"completed", "failed", "skipped", "cancelled", "interrupted"}
            active = {"queued", "waiting_input", "planning", "generating", "validating", "running", "verifying", "repairing", "paused"}
            # Do not let an old lifecycle event keep a flow node active after a
            # later event in the same flow has completed. The node represents
            # the latest observable state of that flow, not every nested step.
            if previous_status in terminal and step.status in active:
                pass
            else:
                node["status"] = step.status
            if str(step.status or "") in {"completed", "failed", "skipped", "cancelled", "interrupted"}:
                node["progress"] = 100.0
            else:
                node["progress"] = max(float(node.get("progress") or 0.0), float(step.progress or 0.0))
            node["active"] = str(node.get("status") or step.status) not in terminal
            node["last_step_id"] = step.step_id
            node["last_message"] = step.last_message
            node["last_level"] = step.level
            node["last_kind"] = step.kind
            node["method"] = step.method
            node["tool"] = step.tool
            node["input"] = step.input
            node["output"] = step.output
            node["error"] = step.error
            node["trace"] = step.trace
            node["evidence"] = step.evidence
            node["next_action"] = step.next_action
            node["updated_at"] = utc_now()
            break

    def _find_active_step_id(self, run: RuntimeRunState) -> str:
        active_statuses = {"created", "queued", "waiting_input", "planning", "generating", "validating", "running", "verifying", "repairing", "paused"}
        for step_id, step in reversed(list(run.steps.items())):
            if step.status in active_statuses:
                return step_id
        return ""

    def _recalculate_run_progress(self, run: RuntimeRunState) -> None:
        if not run.steps:
            return
        terminal_statuses = {"completed", "failed", "skipped", "cancelled", "interrupted"}
        active_statuses = {"created", "queued", "waiting_input", "planning", "generating", "validating", "running", "verifying", "repairing", "paused"}
        # Use observable flow nodes as the user-facing progress model. This
        # avoids a single long-lived wrapper step (for example the UI/request
        # lifecycle) making the whole run look stuck while inner stages advance.
        flow_values = []
        for node in run.flow or []:
            status = str(node.get("status") or "created")
            if status in {"skipped", "cancelled"}:
                continue
            if status in {"created", "not_started", "pending"}:
                flow_values.append(0.0)
            else:
                flow_values.append(float(node.get("progress") or 0.0))
        values = flow_values or [float(step.progress or 0.0) for step in run.steps.values()]
        run.progress = max(0.0, min(100.0, sum(values) / max(1, len(values))))
        if any(step.status == "failed" for step in run.steps.values()):
            run.status = "failed"
            return
        active_step = self._find_active_step_id(run)
        run.active_step_id = active_step
        if not active_step and run.steps and all(step.status in terminal_statuses for step in run.steps.values()):
            run.status = "completed"
            run.progress = 100.0

    def _safe_id(self, value: str) -> str:
        raw = str(value or "runtime")[:160]
        safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in raw).strip("._")
        return safe or "runtime"

    def _safe_step_id(self, value: str) -> str:
        return self._safe_id(value or "runtime")

    def _redact_data(self, data: Any) -> Any:
        if isinstance(data, dict):
            out = {}
            for k, v in data.items():
                key = str(k)
                if any(s in key.casefold() for s in ("secret", "password", "token", "apikey", "api_key", "authorization")):
                    out[key] = "***REDACTED***"
                else:
                    out[key] = self._redact_data(v)
            return out
        if isinstance(data, list):
            return [self._redact_data(x) for x in data[:500]]
        if isinstance(data, str):
            return data[-8000:]
        return data


runtime_state_manager = RuntimeStateManager()

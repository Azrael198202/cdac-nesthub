from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterable

from ai_core.config.paths import RUNTIME_TRACES
from ai_core.runtime.observability.runtime_console import emit_console_event
from .contracts import RuntimeRunState, RuntimeStateEvent, RuntimeStepState, utc_now


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
            self._runs[run_id] = run
            self._write_run(run)
        self.emit(run_id=run_id, step_id="runtime", kind="lifecycle", level="user", status="running", title="Run started", message=run.title, progress=0, metadata=metadata or {})
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
            step_id="runtime",
            kind="output" if run.status == "completed" else "error",
            level="user" if run.status == "completed" else "developer",
            status=run.status,
            title="Run finished",
            message=summary or run.status,
            output=output,
            error=error,
            progress=100.0 if run.status == "completed" else None,
        )
        return run.to_dict()

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
        with self._lock:
            run = self._runs.get(run_id) or self._read_run(run_id) or RuntimeRunState(run_id=run_id, title=run_id)
            seq = self._sequence.get(run_id, int(run.event_count or 0)) + 1
            self._sequence[run_id] = seq
            event = RuntimeStateEvent(
                run_id=run_id,
                task_id=task_id or run.task_id,
                step_id=step_id,
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
                progress=progress,
                started_at=now if status in {"running", "planning", "generating", "validating", "verifying", "repairing"} else None,
                ended_at=now if status in {"completed", "failed", "skipped", "cancelled"} else None,
                error=self._redact_data(error) if error else None,
                trace=self._redact_data(trace or {}),
                evidence=self._redact_data(evidence or []),
                next_action=next_action,
                metadata=self._redact_data(metadata or {}),
            ).to_dict()
            step = run.steps.get(step_id) or RuntimeStepState(step_id=step_id, name=title or step_id)
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
            if progress is not None:
                try:
                    step.progress = max(0.0, min(100.0, float(progress)))
                except Exception:
                    pass
            if status in {"running", "planning", "generating", "validating", "verifying", "repairing"}:
                step.started_at = step.started_at or now
            if status in {"completed", "failed", "skipped", "cancelled"}:
                step.ended_at = now
                if status == "completed" and progress is None:
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
            run.status = "failed" if status == "failed" else ("running" if run.status in {"created", "queued"} else run.status)
            run.updated_at = now
            run.active_step_id = step_id if status not in {"completed", "failed", "skipped"} else run.active_step_id
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
        for key in ("task_id", "status", "title", "created_at", "updated_at", "started_at", "ended_at", "progress", "active_step_id", "summary", "metadata", "event_count", "last_event_id", "last_error"):
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
            run.steps[step.step_id] = step
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

    def _recalculate_run_progress(self, run: RuntimeRunState) -> None:
        if not run.steps:
            return
        values = [float(step.progress or 0.0) for step in run.steps.values()]
        run.progress = max(0.0, min(100.0, sum(values) / max(1, len(values))))
        if any(step.status == "failed" for step in run.steps.values()):
            run.status = "failed"

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

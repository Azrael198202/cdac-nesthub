from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


STATE_STATUSES = {
    "created",
    "queued",
    "waiting_input",
    "planning",
    "generating",
    "validating",
    "running",
    "verifying",
    "repairing",
    "completed",
    "failed",
    "cancelled",
    "paused",
    "skipped",
}

VISIBILITY_LEVELS = {"user", "developer", "advanced", "diagnostic"}
EVENT_KINDS = {
    "lifecycle",
    "input",
    "output",
    "method",
    "tool",
    "progress",
    "api_call",
    "download",
    "install",
    "command",
    "validation",
    "verification",
    "repair",
    "log",
    "error",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_event_id() -> str:
    return f"evt_{uuid4().hex[:16]}"


@dataclass
class RuntimeStateEvent:
    run_id: str
    event_id: str = field(default_factory=new_event_id)
    task_id: str = ""
    step_id: str = "runtime"
    parent_step_id: str = ""
    sequence: int = 0
    ts: str = field(default_factory=utc_now)
    level: str = "developer"
    kind: str = "lifecycle"
    status: str = "running"
    title: str = ""
    message: str = ""
    input: Any | None = None
    output: Any | None = None
    method: str = ""
    tool: str = ""
    progress: float | None = None
    started_at: str | None = None
    ended_at: str | None = None
    error: dict[str, Any] | None = None
    trace: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    next_action: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["level"] = self.level if self.level in VISIBILITY_LEVELS else "developer"
        data["kind"] = self.kind if self.kind in EVENT_KINDS else "log"
        data["status"] = self.status if self.status in STATE_STATUSES else str(self.status or "running")
        if data.get("progress") is not None:
            try:
                data["progress"] = max(0.0, min(100.0, float(data["progress"])))
            except Exception:
                data["progress"] = None
        return data


@dataclass
class RuntimeStepState:
    step_id: str
    name: str = ""
    status: str = "created"
    level: str = "developer"
    kind: str = "lifecycle"
    input: Any | None = None
    output: Any | None = None
    method: str = ""
    tool: str = ""
    progress: float = 0.0
    started_at: str | None = None
    ended_at: str | None = None
    error: dict[str, Any] | None = None
    trace: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    next_action: str = ""
    event_count: int = 0
    last_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status if self.status in STATE_STATUSES else str(self.status or "created")
        data["level"] = self.level if self.level in VISIBILITY_LEVELS else "developer"
        data["kind"] = self.kind if self.kind in EVENT_KINDS else "log"
        data["progress"] = max(0.0, min(100.0, float(self.progress or 0.0)))
        return data


@dataclass
class RuntimeRunState:
    run_id: str
    task_id: str = ""
    status: str = "created"
    title: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    ended_at: str | None = None
    progress: float = 0.0
    active_step_id: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    steps: dict[str, RuntimeStepState] = field(default_factory=dict)
    event_count: int = 0
    last_event_id: str = ""
    last_error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status if self.status in STATE_STATUSES else str(self.status or "created")
        data["progress"] = max(0.0, min(100.0, float(self.progress or 0.0)))
        data["steps"] = [step.to_dict() for step in self.steps.values()]
        return data

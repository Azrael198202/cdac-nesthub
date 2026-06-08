from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ai_core.config.paths import RUNTIME_DIR
from ai_core.runtime.observability.runtime_console import emit_console_event
from ai_core.runtime.state import runtime_state_manager


@dataclass
class StageSpan:
    run_id: str
    stage_id: str
    area: str
    start_time: float
    model_id: str | None = None
    provider: str | None = None
    prompt_trace_path: str | None = None
    output_trace_path: str | None = None


class RuntimeStageObserver:
    """Domain-neutral runtime stage observer.

    It records stage timing, selected model/provider, prompt trace paths,
    output trace paths, and compact execution status. It is observability only:
    no routing, planning, or task-specific decision is made here.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or (RUNTIME_DIR / "traces" / "stage_observer")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def span(self, *, run_id: str, stage_id: str, area: str = "workflow", model_id: str | None = None, provider: str | None = None, metadata: dict[str, Any] | None = None) -> Iterator[StageSpan]:
        span = StageSpan(run_id=run_id, stage_id=stage_id, area=area, start_time=time.perf_counter(), model_id=model_id, provider=provider)
        self.emit(
            run_id=run_id,
            stage_id=stage_id,
            area=area,
            status="running",
            event="stage_started",
            message=f"stage started: {stage_id}",
            duration_ms=0,
            model_id=model_id,
            provider=provider,
            metadata=metadata or {},
        )
        try:
            yield span
        except Exception as exc:
            duration_ms = int((time.perf_counter() - span.start_time) * 1000)
            self.emit(
                run_id=run_id,
                stage_id=stage_id,
                area=area,
                status="failed",
                event="stage_failed",
                message=f"stage failed: {stage_id}",
                duration_ms=duration_ms,
                model_id=span.model_id,
                provider=span.provider,
                prompt_trace_path=span.prompt_trace_path,
                output_trace_path=span.output_trace_path,
                metadata={"error_type": exc.__class__.__name__, "error": str(exc)[:1200]},
            )
            raise
        else:
            duration_ms = int((time.perf_counter() - span.start_time) * 1000)
            self.emit(
                run_id=run_id,
                stage_id=stage_id,
                area=area,
                status="completed",
                event="stage_completed",
                message=f"stage completed: {stage_id}",
                duration_ms=duration_ms,
                model_id=span.model_id,
                provider=span.provider,
                prompt_trace_path=span.prompt_trace_path,
                output_trace_path=span.output_trace_path,
                metadata=metadata or {},
            )

    def emit(self, *, run_id: str, stage_id: str, area: str, status: str, event: str, message: str, duration_ms: int | None = None, model_id: str | None = None, provider: str | None = None, prompt_trace_path: str | None = None, output_trace_path: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "area": area,
            "stage_id": stage_id,
            "event": event,
            "status": status,
            "message": message,
            "duration_ms": duration_ms,
            "model_id": model_id,
            "provider": provider,
            "prompt_trace_path": prompt_trace_path,
            "output_trace_path": output_trace_path,
            "metadata": metadata or {},
        }
        path = self.base_dir / f"{self._safe(run_id)}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        emit_console_event(
            area="stage_observer",
            event=event,
            status=status,
            message=message,
            data={k: v for k, v in payload.items() if k not in {"message"}},
        )
        runtime_state_manager.emit(
            run_id=run_id,
            step_id=stage_id,
            level="developer",
            kind="lifecycle" if event.endswith("started") else ("error" if status == "failed" else "output"),
            status=status,
            title=stage_id,
            message=message,
            method=area,
            tool=provider or model_id or "",
            progress=0 if status == "running" else (100 if status == "completed" else None),
            error=(metadata or {}) if status == "failed" else None,
            trace={"prompt_trace_path": prompt_trace_path, "output_trace_path": output_trace_path},
            metadata={"duration_ms": duration_ms, "model_id": model_id, "provider": provider, **(metadata or {})},
        )
        return payload

    def _safe(self, value: str) -> str:
        return "".join(c if c.isalnum() or c in {"_", "-", "."} else "_" for c in str(value or "run"))[:120] or "run"

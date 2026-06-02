from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.runtime.observability.runtime_console import emit_console_event, set_current_run_id, reset_current_run_id
from apps.api.server import _console_progress_for_run, _normalize_agent_studio_job, _job_progress


def main() -> None:
    run_id = "verify_observability_correlation"
    runtime = Path("runtime")
    (runtime / "logs").mkdir(parents=True, exist_ok=True)
    (runtime / "traces" / "agent_studio_runs").mkdir(parents=True, exist_ok=True)
    log = runtime / "logs" / "runtime_console.jsonl"
    log.write_text("", encoding="utf-8")
    started = time.time()
    token = set_current_run_id(run_id)
    try:
        emit_console_event(area="agent_studio", event="REQUEST_STARTED", status="running", message="runtime request accepted", data={})
        emit_console_event(area="capability_acquisition", event="BlueprintPlanner", status="running", message="Blueprint planning started", data={"stage_label":"BlueprintPlanner", "stage_index":4, "total_stages":14})
        emit_console_event(area="capability_acquisition", event="BlueprintPlanner", status="planned", message="BlueprintPlanner: planned", data={"stage_label":"BlueprintPlanner", "stage_index":4, "total_stages":14})
    finally:
        reset_current_run_id(token)
    job = {"status":"running", "started_at": started, "progress_events":[_job_progress("request accepted", "completed")]}
    progress = _console_progress_for_run(run_id, started_at=started)
    assert any(item.get("stage") == "BlueprintPlanner" for item in progress), progress
    normalized = _normalize_agent_studio_job(run_id, job)
    assert normalized.get("current_stage") == "BlueprintPlanner", normalized
    assert normalized.get("total_steps") == 14, normalized
    print(json.dumps({"ok": True, "current_stage": normalized.get("current_stage"), "total_steps": normalized.get("total_steps")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

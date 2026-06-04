from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_core.runtime.scheduler import ScheduledTaskRunner


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = root / "runtime" / "generated" / "tasks"
        trace_dir = root / "runtime" / "traces" / "scheduled_tasks"
        tasks_dir.mkdir(parents=True)
        task_path = tasks_dir / "SendMailTask.json"
        task_path.write_text(json.dumps({
            "task_name": "SendMailTask",
            "selected_participant_ids": ["controller", "payload"],
            "schedule_policy": {
                "enabled": True,
                "mode": "recurring",
                "interval_seconds": 60,
                "next_run_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                "controller_participant_ids": ["controller"],
            },
            "runtime_parameters": {"to": "x@example.com", "subject": "s", "body": "b", "interval": "60s"},
            "tasks": [{"participant_id": "controller"}, {"participant_id": "payload"}],
        }), encoding="utf-8")

        calls: list[dict] = []

        async def executor(task_name: str, task_graph: dict) -> dict:
            policy = task_graph.get("schedule_policy") or {}
            controllers = set(policy.get("controller_participant_ids") or [])
            selected = task_graph.get("selected_participant_ids") or []
            payload = [x for x in selected if x not in controllers]
            calls.append({"task_name": task_name, "payload": payload})
            return {"status": "completed", "run_id": "run_test"}

        runner = ScheduledTaskRunner(tasks_dir=tasks_dir, trace_dir=trace_dir)
        await runner.run_once(executor)

        assert calls == [{"task_name": "SendMailTask", "payload": ["payload"]}]
        updated = json.loads(task_path.read_text(encoding="utf-8"))
        assert updated["schedule_policy"].get("last_run_at")
        assert updated["schedule_policy"].get("next_run_at")
        log_text = (trace_dir / "scheduler.jsonl").read_text(encoding="utf-8")
        for event in [
            "scheduler_tick",
            "due_task_found",
            "dispatch_started",
            "dispatch_completed",
            "next_run_at_updated",
        ]:
            assert f'"event": "{event}"' in log_text, event
        assert "skipped_controller_participants" in log_text
        print("scheduled runtime generation verification passed")


if __name__ == "__main__":
    asyncio.run(main())

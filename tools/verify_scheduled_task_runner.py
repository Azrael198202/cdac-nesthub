from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_core.runtime.scheduler import ScheduledTaskRunner


def test_scheduled_runner_executes_and_advances_next_run():
    with tempfile.TemporaryDirectory() as tmp:
        tasks_dir = Path(tmp) / "tasks"
        traces_dir = Path(tmp) / "traces"
        tasks_dir.mkdir(parents=True)
        task_path = tasks_dir / "ExampleTask.json"
        task_path.write_text(json.dumps({
            "task_name": "ExampleTask",
            "schedule_policy": {
                "enabled": True,
                "mode": "recurring",
                "interval_seconds": 60,
                "next_run_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            },
        }), encoding="utf-8")
        calls = []
        async def executor(task_name: str):
            calls.append(task_name)
            return {"status": "completed", "run_id": "run_test"}
        runner = ScheduledTaskRunner(tasks_dir=tasks_dir, trace_dir=traces_dir)
        executed = asyncio.run(runner.run_once(executor))
        assert calls == ["ExampleTask"]
        assert executed[0]["task_name"] == "ExampleTask"
        updated = json.loads(task_path.read_text(encoding="utf-8"))
        assert updated["schedule_policy"].get("last_run_at")
        assert updated["schedule_policy"].get("next_run_at")
        assert "scheduled_task_executed" in (traces_dir / "scheduler.jsonl").read_text(encoding="utf-8")


if __name__ == "__main__":
    test_scheduled_runner_executes_and_advances_next_run()
    print("scheduled task runner verification passed")

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from auxiliary_brain.runtime.scheduler.scheduled_task_runner import ScheduledTaskRunner


def _write_due_task(path: Path, *, name: str, schedule_instance_id: str) -> None:
    due_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    path.write_text(
        json.dumps(
            {
                "task_name": name,
                "selected_participant_ids": ["payload"],
                "tasks": [{"participant_id": "payload", "step_type": "generic"}],
                "schedule_policy": {
                    "enabled": True,
                    "state": "active",
                    "mode": "recurring",
                    "interval_seconds": 60,
                    "next_run_at": due_at,
                    "schedule_instance_id": schedule_instance_id,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


async def _run_two_due_tasks(tmp_path: Path):
    tasks_dir = tmp_path / "tasks"
    trace_dir = tmp_path / "traces"
    tasks_dir.mkdir()
    _write_due_task(tasks_dir / "task_a.json", name="task_a", schedule_instance_id="schedule_a")
    _write_due_task(tasks_dir / "task_b.json", name="task_b", schedule_instance_id="schedule_b")

    runner = ScheduledTaskRunner(tasks_dir=tasks_dir, trace_dir=trace_dir)
    calls = []

    async def executor(task_name, task_graph):
        calls.append(
            {
                "task_name": task_name,
                "thread_id": threading.get_ident(),
                "worker_id": task_graph.get("schedule_policy", {}).get("worker_id"),
                "scope": task_graph.get("scheduled_execution_scope"),
            }
        )
        await asyncio.sleep(0.1)
        return {"status": "completed", "run_id": task_graph.get("schedule_policy", {}).get("worker_id")}

    dispatched = await runner.run_once(executor)
    await asyncio.sleep(0.5)
    return dispatched, calls


def test_scheduled_tasks_are_dispatched_to_isolated_workers(tmp_path):
    dispatched, calls = asyncio.run(_run_two_due_tasks(tmp_path))

    assert {item["status"] for item in dispatched} == {"dispatched"}
    assert {item["task_name"] for item in dispatched} == {"task_a", "task_b"}
    assert len(calls) == 2
    assert all(call["worker_id"] for call in calls)
    assert len({call["worker_id"] for call in calls}) == 2
    assert all(call["scope"]["isolation"] == "private_thread_private_event_loop" for call in calls)

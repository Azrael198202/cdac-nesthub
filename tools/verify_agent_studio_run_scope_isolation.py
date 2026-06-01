from __future__ import annotations

import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auxiliary_brain.storage import JsonStore
from auxiliary_brain.studio.service import AgentStudioService


def main() -> None:
    root = Path(tempfile.mkdtemp()) / "runtime"
    store = JsonStore(root=root)
    service = AgentStudioService(store=store)

    store.write_json("generated/agents/current.json", {
        "participant_id": "participant_current",
        "name": "Current participant",
        "client_run_id": "ui_current",
    })
    store.write_json("generated/agents/old.json", {
        "participant_id": "participant_old",
        "name": "Old participant",
        "client_run_id": "ui_old",
    })
    store.write_json("generated/tasks/current_task.json", {
        "graph_id": "graph_current",
        "task_name": "task_current",
        "client_run_id": "ui_current",
        "selected_participant_ids": ["participant_current"],
    })
    store.write_json("generated/tasks/old_task.json", {
        "graph_id": "graph_old",
        "task_name": "task_old",
        "client_run_id": "ui_old",
        "selected_participant_ids": ["participant_old"],
    })
    store.write_json("generated/results/current_run.json", {
        "run_id": "run_current",
        "client_run_id": "ui_current",
        "task_name": "task_current",
        "status": "completed",
    })
    store.write_json("generated/results/old_run.json", {
        "run_id": "run_old",
        "client_run_id": "ui_old",
        "task_name": "task_old",
        "status": "completed",
    })

    participant_view = service.snapshot(
        active_run_id="ui_current",
        scope_kind="participant",
        scope_id="participant_current",
    )
    assert [p["participant_id"] for p in participant_view["participants"]] == ["participant_current"]
    assert participant_view["task_graphs"] == []
    assert participant_view["task_runs"] == []

    task_view = service.snapshot(
        active_run_id="ui_current",
        scope_kind="task",
        scope_id="task_current",
    )
    assert [g["task_name"] for g in task_view["task_graphs"]] == ["task_current"]
    assert [p["participant_id"] for p in task_view["participants"]] == ["participant_current"]
    assert all(r.get("run_id") != "run_old" for r in task_view["task_runs"])

    run_view = service.snapshot(active_run_id="ui_current", scope_kind="request", scope_id="")
    assert [p["participant_id"] for p in run_view["participants"]] == ["participant_current"]
    assert [g["task_name"] for g in run_view["task_graphs"]] == ["task_current"]
    assert [r["run_id"] for r in run_view["task_runs"]] == ["run_current"]
    print("verify_agent_studio_run_scope_isolation: ok")


if __name__ == "__main__":
    main()

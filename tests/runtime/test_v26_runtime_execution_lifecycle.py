from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from auxiliary_brain.scheduler import RuntimeTriggerParser, RuntimeScheduler
from auxiliary_brain.studio.service import AgentStudioService
from auxiliary_brain.execution import RuntimeExecutionRuntime


def test_v26_parses_clock_activation_structure() -> None:
    parsed = RuntimeTriggerParser().parse("run at 10:10 AM", default_timezone="Asia/Tokyo")
    assert parsed["mode"] == "scheduled"
    assert parsed["metadata"]["trigger_type"] == "time"
    assert parsed["metadata"]["expression"] == "10:10 AM"
    assert parsed["metadata"]["timezone"] == "Asia/Tokyo"
    assert parsed["metadata"]["scheduled_at"]


def test_v26_registers_scheduler_instance(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    scheduler = RuntimeScheduler(runtime_root)
    activation = {
        "activation_id": "a1",
        "mode": "scheduled",
        "expression": "10:10 AM",
        "timezone": "Asia/Tokyo",
        "metadata": {"scheduled_at": (datetime.now().astimezone() + timedelta(seconds=60)).isoformat()},
    }
    result = scheduler.register(graph_id="g1", graph_path="runtime/generated/tasks/g1.json", activation=activation)
    assert result["schedule"]["status"] == "scheduled"
    assert (runtime_root / "generated" / "schedules" / f"{result['schedule']['schedule_id']}.json").exists()
    assert (runtime_root / "instances" / f"{result['instance']['instance_id']}.json").exists()


def test_v26_service_creates_live_graph_with_activation(tmp_path: Path) -> None:
    service = AgentStudioService(runtime_root=tmp_path / "runtime", command_config_path="configs/agent_studio_commands.json")
    service.handle_message("Create a time alert agent.")
    service.handle_message("Create a weather forecast agent.")
    result = service.handle_message("Create a task: Alarm woke me up at 10:10 AM and tell me the weather forecast for Fukuoka that day.")
    state = result["state"]
    assert result["registration"]["schedule"]["status"] == "scheduled"
    assert state["task_graphs"]
    graph = state["task_graphs"][0]
    assert graph["activations"][0]["metadata"]["trigger_type"] == "time"
    assert graph["tasks"]
    assert state["instances"]


def test_v26_due_execution_dispatches_tools_and_delivery(tmp_path: Path, monkeypatch) -> None:
    service = AgentStudioService(runtime_root=tmp_path / "runtime", command_config_path="configs/agent_studio_commands.json")
    service.handle_message("Create a time alert agent.")
    created = service.handle_message("Create a task: run at 10:10 AM and collect generated material.")
    schedule = created["registration"]["schedule"]
    schedule_path = tmp_path / "runtime" / "generated" / "schedules" / f"{schedule['schedule_id']}.json"
    payload = json.loads(schedule_path.read_text(encoding="utf-8"))
    payload["activation"]["metadata"]["scheduled_at"] = (datetime.now().astimezone() - timedelta(seconds=1)).isoformat()
    schedule_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def fake_discovery(self, query: str):
        return {"status": "success", "query": query, "results": [{"title": "sample", "snippet": "sample material"}], "selected_document": {"text_excerpt": "sample material"}}

    monkeypatch.setattr("auxiliary_brain.execution.tool_runtime.RuntimeToolRuntime._public_discovery", fake_discovery)
    results = service.run_due_tasks()["results"]
    assert results
    assert results[0]["status"] == "completed"
    assert (tmp_path / "runtime" / "generated" / "tool_outputs").exists()
    assert (tmp_path / "runtime" / "deliveries").exists()


def test_v26_auxiliary_source_does_not_contain_home_experience_terms() -> None:
    root = Path(__file__).resolve().parents[2] / "auxiliary_brain"
    forbidden = ["recipe", "breakfast", "lunch", "home_assistant"]
    hits = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for term in forbidden:
            if term in text:
                hits.append((str(path.relative_to(root)), term))
    assert hits == []

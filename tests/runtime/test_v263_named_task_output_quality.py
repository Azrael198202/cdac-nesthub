from __future__ import annotations

import json
from pathlib import Path

from auxiliary_brain.studio.service import AgentStudioService


def test_named_task_uses_agent_instructions_and_executes(tmp_path: Path) -> None:
    service = AgentStudioService(runtime_root=tmp_path / "runtime")
    service.handle_message("Create an agent named Time Agent to remind you of the current time.")
    service.handle_message("Create an agent named Weather Agent to obtain the weather information for Fukuoka today and tomorrow.")
    created = service.handle_message("Create a task named taskA, which calls the time agent and the weather agent.")
    assert created["task_name"] == "taskA"
    graph = created["state"]["task_graphs"][0]
    objectives = [task["objective"] for task in graph["tasks"]]
    assert any("current time" in item.lower() for item in objectives)
    assert any("Fukuoka today and tomorrow" in item for item in objectives)

    executed = service.handle_message("execute TaskA")
    assert executed["status"] == "completed"
    outputs = executed["result"]["outputs"]
    output_text = json.dumps(outputs, ensure_ascii=False)
    assert "Agent Development Kit" not in output_text
    assert "current time" in output_text.lower() or "iso_time" in output_text
    assert "Fukuoka" in output_text
    assert executed["result"]["delivery"]["channel"] == "console"

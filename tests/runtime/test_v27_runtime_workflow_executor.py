from __future__ import annotations

import json
from pathlib import Path

from auxiliary_brain.studio.service import AgentStudioService


def test_v27_execute_named_task_uses_main_brain_workflow_executor(tmp_path: Path, monkeypatch) -> None:
    service = AgentStudioService(runtime_root=tmp_path / "runtime")
    service.handle_message("Create an agent named Signal Agent to remind you of the current time.")
    service.handle_message("Create an agent named Collector Agent to obtain the external information for TargetPlace today and tomorrow.")
    created = service.handle_message("Create a task named graphAlpha, which calls the signal participant and the collector participant.")
    assert created["task_name"] == "graphAlpha"
    graph = created["state"]["task_graphs"][0]
    assert graph["tasks"][0]["objective"].lower().startswith("obtain") or graph["tasks"][1]["objective"].lower().startswith("obtain")

    def fake_discovery(self, query: str):
        return {
            "status": "success",
            "query": query,
            "results": [{"title": "local result", "snippet": "two-day material for requested place"}],
            "selected_document": {"status": "success", "text_excerpt": "verified two-day material for requested place"},
        }

    monkeypatch.setattr("ai_core.agent_execution.core_task_executor.AICoreAgentTaskExecutor._public_discovery", fake_discovery)
    executed = service.handle_message("execute TaskA")
    assert executed["status"] == "completed"
    outputs = executed["result"]["outputs"]
    assert outputs
    assert all(item.get("origin") == "ai_core" for item in outputs.values())
    assert any(item.get("workflow_plan") for item in outputs.values())
    text = json.dumps(outputs, ensure_ascii=False)
    assert "Create a task named" not in text
    assert "workflow_events" in text
    assert "verified two-day material" in text
    assert executed["result"]["delivery"]["upstream_origin"] == "ai_core"

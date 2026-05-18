from __future__ import annotations

import json
from pathlib import Path

from auxiliary_brain.studio.service import AgentStudioService


def test_v272_execute_named_task_uses_configured_main_brain_tool(tmp_path: Path, monkeypatch) -> None:
    service = AgentStudioService(runtime_root=tmp_path / "runtime")
    service.handle_message("Create an agent named Time Agent to remind you of the current time.")
    service.handle_message("Create an agent named Weather Agent to obtain the weather information for Fukuoka today and tomorrow.")
    service.handle_message("Create a task named taskA, which calls the time agent and the weather agent.")

    def fake_configured_collection(self, *, profile, query):
        return {
            "status": "success",
            "query": query,
            "url": "https://example.test/runtime-configured",
            "result_text": "Configured runtime result for Fukuoka\nCurrent temperature: 22 C\nSecond max: 24 C",
            "response_status": 200,
        }

    monkeypatch.setattr(
        "ai_core.agent_execution.core_task_executor.AICoreAgentTaskExecutor._configured_collection",
        fake_configured_collection,
    )

    executed = service.handle_message("execute TaskA")
    assert executed["status"] == "completed"
    result = executed["result"]
    outputs = result["outputs"]
    assert result["execution_mode"] == "ai_core_primary_orchestration"
    assert all(item.get("origin") == "ai_core" for item in outputs.values())
    text = json.dumps(outputs, ensure_ascii=False)
    assert "Configured runtime result for Fukuoka" in text
    assert "Current temperature: 22 C" in text
    assert "obtain the weather information" not in outputs[next(iter(outputs))].get("result_text", "")
    assert result["delivery"].get("upstream_origin") == "ai_core"

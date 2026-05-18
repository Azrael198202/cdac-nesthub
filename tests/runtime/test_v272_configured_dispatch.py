from __future__ import annotations

import json
from pathlib import Path

from auxiliary_brain.studio.service import AgentStudioService


def test_v272_execute_named_task_uses_configured_main_brain_tool(tmp_path: Path, monkeypatch) -> None:
    service = AgentStudioService(runtime_root=tmp_path / "runtime")
    service.handle_message("Create an agent named Signal Agent to provide a runtime snapshot.")
    service.handle_message("Create an agent named Collector Agent to obtain external information for TargetPlace.")
    service.handle_message("Create a task named graphAlpha, which calls the signal participant and the collector participant.")

    def fake_load_config(self):
        return {
            "profiles": [
                {
                    "profile_id": "generic_configured_profile",
                    "operation": "configured_http_json",
                    "match_terms": ["external", "information"],
                    "parameters": [{"name": "target", "patterns": [r"for\\s+([A-Za-z][A-Za-z .,'-]{1,80})"], "default": "TargetPlace"}],
                    "requests": [{"url_template": "https://example.test/{target}", "response_type": "json"}],
                }
            ],
            "text_cleanup": {"drop_phrases": ["create a task", "named", "which calls", "calls", "participant", "execute", "task"]},
        }

    def fake_configured_collection(self, *, profile, query):
        return {
            "status": "success",
            "query": query,
            "url": "https://example.test/runtime-configured",
            "result_text": "Configured runtime result for TargetPlace\nPrimary value: 22\nSecondary value: 24",
            "response_status": 200,
        }

    monkeypatch.setattr("ai_core.agent_execution.core_task_executor.AICoreAgentTaskExecutor._load_config", fake_load_config)
    monkeypatch.setattr("ai_core.agent_execution.core_task_executor.AICoreAgentTaskExecutor._configured_collection", fake_configured_collection)

    executed = service.handle_message("execute graphAlpha")
    assert executed["status"] == "completed"
    result = executed["result"]
    outputs = result["outputs"]
    assert result["execution_mode"] == "ai_core_primary_orchestration"
    assert all(item.get("origin") == "ai_core" for item in outputs.values())
    text = json.dumps(outputs, ensure_ascii=False)
    assert "Primary value: 22" in text
    assert "Secondary value: 24" in text
    assert "obtain external information" not in outputs[next(iter(outputs))].get("result_text", "")
    assert result["delivery"].get("upstream_origin") == "ai_core"

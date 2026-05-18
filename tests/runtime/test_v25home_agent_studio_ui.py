from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.server import app, studio_service
from auxiliary_brain.studio.config_loader import StudioCommandConfig
from auxiliary_brain.studio.service import AgentStudioService


def test_command_phrases_are_loaded_from_config() -> None:
    config = StudioCommandConfig("configs/agent_studio_commands.json")
    payload = config.load()
    assert payload["actions"]
    assert config.detect_action(payload["actions"][0]["patterns"][0]) == payload["actions"][0]["action"]


def test_studio_service_generates_runtime_artifacts(tmp_path: Path) -> None:
    service = AgentStudioService(runtime_root=tmp_path, command_config_path="configs/agent_studio_commands.json")
    command = StudioCommandConfig("configs/agent_studio_commands.json").load()["actions"][0]["patterns"][0]
    result = service.handle_message(f"{command} alpha beta gamma")
    assert result["origin"] == "auxiliary_brain"
    assert result["action"] == "create_participant"
    state = result["state"]
    assert state["agents"]
    assert state["traces"]


def test_studio_service_creates_and_controls_task_graph(tmp_path: Path) -> None:
    service = AgentStudioService(runtime_root=tmp_path, command_config_path="configs/agent_studio_commands.json")
    payload = StudioCommandConfig("configs/agent_studio_commands.json").load()
    create_agent = payload["actions"][0]["patterns"][0]
    create_task = payload["actions"][1]["patterns"][0]
    service.handle_message(f"{create_agent} alpha beta")
    task_result = service.handle_message(f"{create_task} neutral objective")
    assert task_result["graph_id"]
    started = service.update_latest_task_graph("running", "manual")
    stopped = service.update_latest_task_graph("stopped", "manual")
    assert started["status"] == "running"
    assert stopped["status"] == "stopped"
    assert stopped["state"]["task_runs"][0]["status"] == "stopped"


def test_agent_studio_page_and_apis_are_available() -> None:
    client = TestClient(app)
    page = client.get("/agent-studio")
    assert page.status_code == 200
    assert "Runtime Agent Studio" in page.text
    commands = client.get("/api/agent-studio/commands")
    assert commands.status_code == 200
    assert commands.json()["actions"]
    response = client.post("/api/agent-studio/message", json={"message": "create agent alpha beta"})
    assert response.status_code == 200
    assert response.json()["origin"] == "auxiliary_brain"


def test_original_web_page_is_not_replaced() -> None:
    original = Path("apps/web/index.html").read_text(encoding="utf-8")
    new_page = Path("apps/web/agent_studio.html").read_text(encoding="utf-8")
    assert original != new_page
    assert "Runtime Agent Studio" not in original

from pathlib import Path

from auxiliary_brain.studio.service import AgentStudioService


def test_named_task_is_created_then_executed_on_explicit_command(tmp_path: Path) -> None:
    service = AgentStudioService(runtime_root=tmp_path, command_config_path="configs/agent_studio_commands.json")

    service.handle_message("Create an agent named Time Agent to remind you of the current time.")
    service.handle_message("Create an agent named Weather Agent to obtain the weather information for Fukuoka today and tomorrow.")

    created = service.handle_message("Create a task named taskA, which calls the time agent and the weather agent.")
    assert created["status"] == "completed"
    assert created["task_name"] == "taskA"
    assert created["state"]["task_runs"][0]["status"] == "created"
    assert created["state"]["deliveries"] == []

    executed = service.handle_message("execute TaskA")
    assert executed["action"] == "execute_task_graph"
    assert executed["status"] == "completed"
    assert executed["task_name"] == "taskA"
    assert executed["result"]["blocked_task_ids"] == []
    assert len(executed["result"]["executed_task_ids"]) == 3
    assert executed["state"]["deliveries"]
    assert executed["state"]["tool_outputs"]

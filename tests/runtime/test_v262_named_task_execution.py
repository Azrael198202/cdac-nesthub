from pathlib import Path

from auxiliary_brain.studio.service import AgentStudioService


def test_named_task_is_created_then_executed_on_explicit_command(tmp_path: Path) -> None:
    service = AgentStudioService(runtime_root=tmp_path, command_config_path="configs/agent_studio_commands.json")

    service.handle_message("Create an agent named Signal Agent to remind you of the current time.")
    service.handle_message("Create an agent named Collector Agent to obtain the external information for TargetPlace today and tomorrow.")

    created = service.handle_message("Create a task named graphAlpha, which calls the signal participant and the collector participant.")
    assert created["status"] == "completed"
    assert created["task_name"] == "graphAlpha"
    assert created["state"]["task_runs"][0]["status"] == "created"
    assert created["state"]["deliveries"] == []

    executed = service.handle_message("execute TaskA")
    assert executed["action"] == "execute_task_graph"
    assert executed["status"] == "completed"
    assert executed["task_name"] == "graphAlpha"
    assert executed["result"]["blocked_task_ids"] == []
    assert len(executed["result"]["executed_task_ids"]) == 3
    assert executed["state"]["deliveries"]
    assert executed["state"]["tool_outputs"]

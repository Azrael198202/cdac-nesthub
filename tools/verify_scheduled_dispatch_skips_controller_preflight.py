from __future__ import annotations

import tempfile
from pathlib import Path

from auxiliary_brain.storage import JsonStore
from auxiliary_brain.studio.service import AgentStudioService


def _contract(*names: str) -> dict:
    return {
        "contract_type": "agent_parameter_contract",
        "collection_policy": {"blocking": True},
        "parameters": [
            {
                "name": name,
                "label": name,
                "description": f"Provide {name}.",
                "required": True,
                "values": [],
                "runtime_required": True,
                "blocking": True,
                "execution_required": True,
            }
            for name in names
        ],
        "missing_information": [],
    }


def test_scheduled_dispatch_preflight_ignores_controller_participant():
    with tempfile.TemporaryDirectory() as tmp:
        service = AgentStudioService(store=JsonStore(Path(tmp) / "runtime"))
        controller = {
            "participant_id": "controller_1",
            "display_name": "Controller Participant",
            "parameter_contract": _contract("operation", "name"),
        }
        payload = {
            "participant_id": "payload_1",
            "display_name": "Payload Participant",
            "parameter_contract": _contract("target_value"),
        }
        task_graph = {
            "task_name": "ExampleScheduledTask",
            "selected_participant_ids": ["controller_1", "payload_1"],
            "schedule_policy": {
                "enabled": True,
                "mode": "recurring",
                "interval_seconds": 60,
                "controller_participant_ids": ["controller_1"],
            },
            "tasks": [],
        }
        ready = service._preflight_runtime_parameters(
            task_graph,
            [controller, payload],
            {"_scheduled_dispatch": True, "target_value": "ok"},
        )
        assert ready["status"] == "ready", ready

        blocked = service._preflight_runtime_parameters(
            task_graph,
            [controller, payload],
            {"_scheduled_dispatch": True},
        )
        assert blocked["status"] == "requires_input", blocked
        parameter_names = {str(item.get("parameter_name") or item.get("name") or "") for item in blocked.get("missing_inputs", []) if isinstance(item, dict)}
        assert any("target_value" in item for item in parameter_names), parameter_names
        assert not any(item.endswith(".operation") or item == "operation" for item in parameter_names), parameter_names
        assert not any(item.endswith(".name") or item == "name" for item in parameter_names), parameter_names


if __name__ == "__main__":
    test_scheduled_dispatch_preflight_ignores_controller_participant()
    print("scheduled dispatch controller preflight verification passed")

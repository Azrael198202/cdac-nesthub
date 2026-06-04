from __future__ import annotations

from auxiliary_brain.studio.service import AgentStudioService
from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime
from ai_core.runtime.capability.registered_tool_parameter_bridge import RegisteredToolParameterBridge


def main() -> None:
    material = 'Ask Example Agent to use address alpha.beta123@example.test with subject "sample".'
    svc = AgentStudioService()
    context = svc._structural_source_runtime_context(task_graph={"instruction": material}, instruction=material)
    assert context.get("_original_user_material") == material
    assert context.get("_detected_structural_values", {}).get("electronic_address") == ["alpha.beta123@example.test"]

    participant = {
        "participant_id": "participant_test",
        "display_name": "Example Agent",
        "runtime_parameters": {},
        "parameter_contract": {"parameters": []},
        "capability_profile": {
            "tool_summary": {
                "input_schema": {
                    "type": "object",
                    "required": ["target", "subject"],
                    "properties": {
                        "target": {"type": "array", "items": {"type": "string", "format": "email"}},
                        "subject": {"type": "string"},
                    },
                }
            }
        },
    }
    runtime = AgentDelegationRuntime(store=svc.store)
    runtime._apply_task_runtime_parameters_to_selected([participant], context | {"target": ["alpha"], "subject": "sample"})
    assert participant["runtime_parameters"].get("_original_user_material") == material
    assert participant["runtime_parameters"].get("_detected_structural_values", {}).get("electronic_address") == ["alpha.beta123@example.test"]

    result = RegisteredToolParameterBridge().build_invocation(participant=participant)
    assert result["ok"] is True
    assert result["input_data"]["target"] == ["alpha.beta123@example.test"]
    print("repair_source_material_chain: ok")


if __name__ == "__main__":
    main()

from __future__ import annotations

from ai_core.capabilities.runtime_capability_gap_implementer import RuntimeCapabilityGapImplementer
from ai_core.config.paths import RUNTIME_DIR, RUNTIME_REGISTRY
from ai_core.executors.static_transform_executor import StaticTransformExecutor
from ai_core.tools.runtime_registered_tool_service import RuntimeRegisteredToolService
from ai_core.workflow.workflow_contract_builder import WorkflowContractBuilder


def _reset_runtime_registry_and_connections() -> None:
    for name in ("tool_registry.json", "module_registry.json"):
        path = RUNTIME_REGISTRY / name
        if path.exists():
            path.unlink()
    connections_root = RUNTIME_DIR / "connections"
    if connections_root.exists():
        import shutil
        shutil.rmtree(connections_root)


def test_capability_acquisition_does_not_block_on_research_resolvable_missing_information():
    executor = StaticTransformExecutor()
    input_record = {"missing_information": []}
    intent_record = {
        "intent_type": "runtime_capability_acquisition",
        "capability_gap_detected": True,
        "requires_external_information": True,
        "needs_external_execution": True,
        "external_information_signals": ["capability_gap_resolution"],
        "missing_information": [
            {"name": "implementation_approach"},
            {"name": "authentication_method"},
            {"name": "protocol_details"},
        ],
    }
    result = executor._collect_missing(input_record, intent_record, known={})
    assert result == []

    builder = WorkflowContractBuilder()
    state = {"results": {"intent_recognition": intent_record}}
    assert builder.has_missing_required_input(state=state, result={"missing_information": ["protocol_details"]}) is False


def test_connected_external_message_capability_is_generated_registered_configured_and_approval_gated():
    _reset_runtime_registry_and_connections()
    impl = RuntimeCapabilityGapImplementer()
    result = impl.implement_if_requested(
        user_input=(
            "Acquire runtime capability: Send messages through an external mail service. "
            "Find implementation approaches, generate connection schema, secret schema, "
            "approval policy, tests, register and verify."
        ),
        evidence={"urls": ["https://example.invalid/source-a", "https://example.invalid/source-b"]},
        run_id="test_connected_external_message_capability",
        allow_implementation=True,
    )
    assert result["status"] == "implemented_tested_registered"
    assert result["validation"]["passed"] is True
    assert result["verification_run"]["passed"] is True

    service = RuntimeRegisteredToolService()
    tool_id = "connected_message_delivery_adapter"
    tools = service.list_tools()
    tool = next(t for t in tools if t.get("tool_id") == tool_id)
    assert tool["executable"] is True
    assert tool["connection_schema"]["required"] == ["service_endpoint", "account_identifier", "transport_mode"]
    assert tool["secret_schema"]["required"] == ["primary_credential"]
    assert tool["approval_policy"]["required"] is True

    blocked = service.execute_tool(
        tool_id=tool_id,
        input_data={"message": {"targets": ["a@example.invalid"], "title": "T", "body": "B"}},
        approval_confirmed=True,
    )
    assert blocked["status"] == "requires_configuration"

    configured = service.configure_tool_profile(
        tool_id=tool_id,
        profile_id="default",
        config={"service_endpoint": "local-sandbox", "account_identifier": "tester", "transport_mode": "sandbox"},
        secrets={"primary_credential": "secret-value"},
    )
    assert configured["ok"] is True
    assert configured["profile"]["secret_configured"]["primary_credential"] is True
    assert "secret-value" not in str(configured)

    approval = service.execute_tool(
        tool_id=tool_id,
        input_data={"message": {"targets": ["a@example.invalid"], "title": "T", "body": "B"}},
    )
    assert approval["status"] == "requires_human_confirmation"

    executed = service.execute_tool(
        tool_id=tool_id,
        input_data={"message": {"targets": ["a@example.invalid"], "title": "T", "body": "B"}},
        approval_confirmed=True,
    )
    assert executed["ok"] is True
    assert executed["result"]["data"]["configured"] is True
    assert executed["result"]["data"]["delivery_prepared"] is True
    assert executed["result"]["data"]["external_action_executed"] is False
    assert "secret-value" not in str(executed)

from __future__ import annotations

from ai_core.capabilities.runtime_capability_gap_implementer import RuntimeCapabilityGapImplementer
from ai_core.config.paths import RUNTIME_DIR, RUNTIME_REGISTRY
from ai_core.tools.runtime_registered_tool_service import RuntimeRegisteredToolService


def test_runtime_generated_capability_declares_connection_secret_approval_and_executes_after_profile_setup():
    for name in ("tool_registry.json", "module_registry.json"):
        path = RUNTIME_REGISTRY / name
        if path.exists():
            path.unlink()
    connections_root = RUNTIME_DIR / "connections"
    if connections_root.exists():
        import shutil
        shutil.rmtree(connections_root)

    impl = RuntimeCapabilityGapImplementer()
    result = impl.implement_if_requested(
        user_input="Acquire configured runtime capability with connection profile, secret contract, and approval.",
        evidence={"urls": ["https://example.invalid/a", "https://example.invalid/b"]},
        run_id="test_generic_connection_secret_lifecycle",
        allow_implementation=True,
    )
    assert result["status"] == "implemented_tested_registered"

    service = RuntimeRegisteredToolService()
    tool_id = "configured_runtime_action_probe"
    tools = service.list_tools()
    tool = next(t for t in tools if t.get("tool_id") == tool_id)
    assert tool["connection_schema"]["required"] == ["endpoint", "account"]
    assert tool["secret_schema"]["required"] == ["credential"]
    assert tool["approval_policy"]["required"] is True

    blocked = service.execute_tool(tool_id=tool_id, input_data={"payload": {"x": 1}}, run_id="blocked_run", approval_confirmed=True)
    assert blocked["status"] == "requires_configuration"

    profile = service.configure_tool_profile(
        tool_id=tool_id,
        profile_id="default",
        config={"endpoint": "local", "account": "tester"},
        secrets={"credential": "secret-value"},
    )
    assert profile["ok"] is True
    assert profile["profile"]["secret_configured"]["credential"] is True
    assert "secret-value" not in str(profile)

    needs_approval = service.execute_tool(tool_id=tool_id, input_data={"payload": {"x": 1}}, run_id="approval_run")
    assert needs_approval["status"] == "requires_human_confirmation"

    executed = service.execute_tool(tool_id=tool_id, input_data={"payload": {"x": 1}}, run_id="approved_run", approval_confirmed=True)
    assert executed["ok"] is True
    data = executed["result"]["data"]
    assert data["configured"] is True
    assert data["secret_available"] is True
    assert "credential" in data["secret_keys"]
    assert "secret-value" not in str(executed["result"].get("provenance", {}))

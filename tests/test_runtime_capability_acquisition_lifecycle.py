from __future__ import annotations

from ai_core.capabilities.runtime_capability_gap_implementer import RuntimeCapabilityGapImplementer
from ai_core.config.paths import RUNTIME_REGISTRY
from ai_core.tools.runtime_registered_tool_service import RuntimeRegisteredToolService


def test_docx_runtime_capability_is_implemented_tested_registered_and_executable():
    for name in ("tool_registry.json", "module_registry.json"):
        path = RUNTIME_REGISTRY / name
        if path.exists():
            path.unlink()
    impl = RuntimeCapabilityGapImplementer()
    result = impl.implement_if_requested(
        user_input="Acquire runtime capability: DOCX text extraction. Find a solution and build it.",
        evidence={"urls": ["https://example.invalid/source-a", "https://example.invalid/source-b"]},
        run_id="test_docx_capability_lifecycle",
        allow_implementation=True,
    )
    assert result["status"] == "implemented_tested_registered"
    assert result["dependency_resolution"]["passed"] is True
    assert result["validation"]["passed"] is True
    assert result["verification_run"]["passed"] is True
    assert result["registration"]["status"] == "registered"

    service = RuntimeRegisteredToolService()
    tools = service.list_tools()
    assert any(tool.get("tool_id") == "docx_text_extractor" and tool.get("executable") for tool in tools)

    verification_input = result["verification_run"]["input"]
    run_result = service.execute_tool(tool_id="docx_text_extractor", input_data=verification_input, run_id="test_registered_docx_run")
    assert run_result["ok"] is True
    data = run_result["result"].get("data") or run_result["result"]
    assert data["paragraph_count"] == 2
    assert "Alpha document" in data["text"]

from ai_core.runtime.capability.execution_mode_selector import ExecutionModeSelector
from ai_core.research.web_research_tool import GenericWebResearchTool


def test_locked_web_search_method_routes_to_web_retrieval():
    selector = ExecutionModeSelector()
    step = {
        "execution_method": "web_search",
        "execution_strategy": ["web_search"],
        "source_policy": {"allow_external": True, "requires_live_evidence": True},
    }
    assert selector.select(step=step, plan={}, state={}, capability="generic_information_access") == "web_retrieval"


def test_external_source_policy_does_not_fall_to_runtime_native():
    selector = ExecutionModeSelector()
    step = {
        "source_policy": {"allow_external": True, "requires_live_evidence": True},
    }
    selected = selector.select(step=step, plan={}, state={}, capability="generic_information_access")
    assert selected in {"structured_provider", "web_retrieval"}


def test_locked_api_method_routes_to_structured_provider():
    selector = ExecutionModeSelector()
    step = {"execution_method": "api_call", "execution_strategy": ["api_call"]}
    assert selector.select(step=step, plan={}, state={}, capability="generic_information_access") == "structured_provider"


def test_web_search_direct_url_creates_evidence_result():
    tool = GenericWebResearchTool()
    import asyncio

    result = asyncio.run(tool.search(query="https://example.com/path", max_results=3))
    assert result["status"] == "success"
    assert result["results"][0]["url"] == "https://example.com/path"
    assert result["attempts"][0]["provider"] == "direct_url"


def test_search_result_extractor_normalizes_redirect_url():
    tool = GenericWebResearchTool()
    html = '''
    <html><body>
      <div class="result">
        <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.org%2Fdoc">Example Title</a>
        <a class="result__snippet">Example snippet text</a>
      </div>
    </body></html>
    '''
    results = tool._extract_search_results(html_text=html, query="query", response_status=200, max_results=5)
    assert results[0]["url"] == "https://example.org/doc"
    assert results[0]["title"] == "Example Title"

from ai_core.interaction.conversation_core_runtime import ConversationCoreRuntime


def test_external_information_signals_are_generic_and_source_based():
    runtime = ConversationCoreRuntime()
    signals = runtime._external_information_signals("Please verify the latest official documentation and include URLs")
    assert "freshness_required" in signals
    assert "evidence_required" in signals
    assert "verification_required" in signals
    assert runtime._generic_external_signal("Please verify the latest official documentation and include URLs") is True


def test_capability_gap_signal_requires_action_and_solution_context():
    runtime = ConversationCoreRuntime()
    assert runtime._generic_capability_gap_signal("Find a solution and implement support for this missing runtime operation") is True
    assert runtime._generic_capability_gap_signal("Write a simple explanation") is False


def test_capability_gap_query_adds_generic_implementation_context():
    runtime = ConversationCoreRuntime()
    query = runtime._capability_gap_query("Find a solution and implement support for this missing runtime operation")
    assert "implementation" in query
    assert "official" in query
    assert "validation" in query


def test_capability_gap_request_is_not_feedback_adaptation():
    from ai_core.interaction.natural_conversation import NaturalConversationService
    from ai_core.runtime.adaptation import FeedbackClassifier

    text = "I need to read files from an external site. Current runtime does not have this capability. Find a solution."
    conversation = NaturalConversationService()
    assert conversation.needs_core_conversation_pipeline(text) is True
    feedback = FeedbackClassifier().classify(text, fallback_target="taskMissing")
    assert feedback.get("matched") is True
    # AgentStudioService must preempt this generic negative wording and route it
    # to the core conversation pipeline before handle_feedback is called.

import asyncio


def test_capability_gap_offline_failure_does_not_fallback_to_generic_assistant():
    from ai_core.interaction.conversation_core_runtime import ConversationCoreRuntime

    runtime = ConversationCoreRuntime()
    evidence = {
        "query": "generic capability gap query",
        "attempts": [{"provider": "test_provider", "status": "error", "error": "network unavailable"}],
    }
    material = runtime._capability_gap_answer_material(
        user_input="Implement the missing operation.",
        evidence=evidence,
        implementation={"status": "blocked_without_verified_evidence"},
        material="",
    )
    assert "blocked_without_verified_evidence" in material
    assert "No implementation was generated or registered" in material
    assert "AI runtime assistant" not in material


def test_capability_gap_success_creates_runtime_candidate_artifact(tmp_path, monkeypatch):
    from ai_core.interaction import conversation_core_runtime as module
    from ai_core.interaction.conversation_core_runtime import ConversationCoreRuntime

    monkeypatch.setattr(module, "RUNTIME_GENERATED", tmp_path)
    runtime = ConversationCoreRuntime()
    evidence = {
        "query": "generic capability gap query",
        "urls": ["https://example.invalid/guide"],
        "attempts": [],
    }
    implementation = runtime._capability_gap_resolution_artifact(
        user_input="Implement the missing operation.",
        query="generic capability gap query",
        evidence=evidence,
        material="safe source excerpt",
        run_id="test_run_001",
    )
    assert implementation["status"] == "implementation_candidate_created"
    assert implementation["source_urls"] == ["https://example.invalid/guide"]
    assert implementation["artifact_path"]
    assert (tmp_path / "capability_gap_resolutions" / "test_run_001.json").exists()


def test_runtime_capability_gap_can_implement_test_and_register_from_template(tmp_path, monkeypatch):
    from pathlib import Path
    import json
    from ai_core.capabilities import runtime_capability_gap_implementer as module
    from ai_core.capabilities.runtime_capability_gap_implementer import RuntimeCapabilityGapImplementer

    root = tmp_path
    monkeypatch.setattr(module, "RUNTIME_GENERATED", root / "generated")
    monkeypatch.setattr(module, "RUNTIME_REGISTRY", root / "registry")
    template_path = root / "templates.json"
    tool_code = """
from __future__ import annotations

def run(input_data=None, **kwargs):
    text = '' if input_data is None else str(input_data)
    return {'status': 'completed', 'length': len(text)}
""".strip()
    test_code = """
from tool import run
assert run('abc')['length'] == 3
print('ok')
""".strip()
    template_path.write_text(json.dumps({
        "templates": [{
            "template_id": "generic_test_capability",
            "match_terms": ["generic-test"],
            "required_terms": [],
            "capabilities": ["generic_test_capability"],
            "entrypoint": {"module": "tool.py", "function": "run"},
            "files": [
                {"path": "tool.py", "content": tool_code},
                {"path": "test_tool.py", "content": test_code},
            ],
        }]
    }), encoding="utf-8")
    impl = RuntimeCapabilityGapImplementer(template_path=template_path)
    result = impl.implement_if_requested(
        user_input="please implement generic-test capability",
        evidence={"urls": ["https://example.invalid/source"]},
        run_id="test_run",
        allow_implementation=True,
    )
    assert result["status"] == "implemented_tested_registered"
    assert result["validation"]["passed"] is True
    registry_path = Path(result["registration"]["registry_path"])
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert "generic_test_capability" in registry
    assert Path(result["artifact"]["test_dir"]).exists()
    assert Path(result["artifact"]["test_dir"], "test_report.json").exists()
    module_registry = json.loads((root / "registry" / "module_registry.json").read_text(encoding="utf-8"))
    assert "generic_test_capability" in module_registry


def test_locked_execution_overrides_incomplete_selected_step():
    from ai_core.interaction.conversation_core_runtime import ConversationCoreRuntime

    runtime = ConversationCoreRuntime()
    selected = runtime._selected_step({
        "locked_execution": {"execution_method": "web_search", "capability": "web_retrieval"},
        "planned_steps": [{"step_id": "s1", "execution_ready": True, "execution_method": "model_response", "capability": "stable_synthesis"}],
    })
    assert selected["execution_method"] == "web_search"
    assert selected["capability"] == "web_retrieval"


def test_registered_runtime_tool_service_executes_sandbox_verified_tool(tmp_path):
    import json
    from ai_core.tools.runtime_registered_tool_service import RuntimeRegisteredToolService

    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    tool_file = tool_dir / "tool.py"
    tool_file.write_text("""
def run(input_data=None, **kwargs):
    text = (input_data or {}).get('text', '') if isinstance(input_data, dict) else str(input_data or '')
    return {'status': 'completed', 'data': {'text': text, 'length': len(text)}}
""".strip(), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({
        "generic_registered_tool": {
            "tool_id": "generic_registered_tool",
            "status": "enabled",
            "capability": "generic_runtime_execution",
            "capabilities": ["generic_runtime_execution"],
            "implementation": {"type": "python_module", "module_path": str(tool_file), "function": "run"},
            "verification": {"sandbox_verification": True},
        }
    }), encoding="utf-8")
    service = RuntimeRegisteredToolService(registry_path=registry_path)
    tools = service.list_tools()
    assert tools[0]["executable"] is True
    result = service.execute_tool(tool_id="generic_registered_tool", input_data={"text": "abc"})
    assert result["ok"] is True
    assert result["result"]["data"]["length"] == 3
    assert service.list_tool_runs()
    assert service.list_execution_traces()

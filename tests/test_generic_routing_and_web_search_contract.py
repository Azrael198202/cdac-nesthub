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

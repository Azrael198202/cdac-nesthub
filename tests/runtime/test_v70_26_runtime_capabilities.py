from ai_core.runtime.browser.browser_runtime_adapter import BrowserRuntimeAdapter
from ai_core.runtime.evidence.structured_fact_graph import StructuredFactGraph
from ai_core.runtime.evidence.multi_source_fusion import MultiSourceEvidenceFusion
from ai_core.runtime.routing.cost_aware_router import CostAwareRouter
from ai_core.runtime.observability.runtime_debug_console import RuntimeDebugConsole
from ai_core.runtime.generated_execution.generated_code_runner import GeneratedCodeRunner
from ai_core.runtime.generated_execution.shell_runtime_executor import ShellRuntimeExecutor
from ai_core.runtime.execution_graph_optimizer import ExecutionGraphOptimizer


def test_browser_runtime_extracts_dom_attributes():
    html = '<a title="Record for May 16 2026"><span data-value="19">19</span><img alt="Clear" /></a>'
    result = BrowserRuntimeAdapter().extract_from_markup(url="https://example.test", markup=html)
    assert result.status == "success"
    assert "May 16 2026" in result.attribute_text
    assert "Clear" in result.attribute_text


def test_structured_fact_graph_and_fusion():
    item = {"url": "https://example.test", "dom_evidence_text": "Record for May 16 2026 value 19 unit C"}
    graph = StructuredFactGraph().build(evidence_items=[item], known_parameters={"place": "example", "date": "2026-05-16"})
    assert graph["fact_count"] > 0
    fused = MultiSourceEvidenceFusion().fuse([graph])
    assert fused["fact_count"] > 0


def test_cost_aware_router_prefers_local_low_cost():
    ranked = CostAwareRouter().rank([
        {"id": "remote", "quality": 0.9, "latency_ms": 8000, "unit_cost": 0.5},
        {"id": "local", "quality": 0.75, "latency_ms": 1200, "unit_cost": 0.0, "is_local": True},
    ])
    assert ranked[0]["id"] == "local"


def test_observability_and_graph_optimizer():
    console = RuntimeDebugConsole()
    console.record("start")
    console.record("materialized")
    assert console.assert_seen("start", "materialized")
    strategy = ExecutionGraphOptimizer().optimize(None, {"verified_material_available": True})
    assert "tool_generation" not in strategy


def test_generated_python_and_shell_execution():
    py = GeneratedCodeRunner().run_python('print("ok")')
    assert py["returncode"] == 0
    assert "ok" in py["stdout"]
    sh = ShellRuntimeExecutor().run(["python", "-c", "print('shell-ok')"])
    assert sh["returncode"] == 0
    assert "shell-ok" in sh["stdout"]

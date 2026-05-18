import asyncio

from jsonschema import validate

from ai_core.runtime.aggregation.sequence_synthesizer import SequenceSynthesizer
from ai_core.runtime.aggregation.stable_synthesizer import StableSynthesizer
from ai_core.runtime.browser.playwright_browser_runtime import PlaywrightBrowserRuntime
from ai_core.runtime.evidence.evidence_verifier import EvidenceVerifier
from ai_core.runtime.mcp.universal_mcp_runtime import UniversalMCPRuntime
from ai_core.runtime.repair.self_healing_runtime import SelfHealingRuntime
from ai_core.runtime.retrieval.parallel_retrieval import ParallelRetrievalRuntime
from ai_core.runtime.routing.route_optimizer import RouteOptimizer
from ai_core.runtime.schemas.runtime_schema_generator import RuntimeSchemaGenerator
from ai_core.runtime.tasking.task_decomposition_graph import TaskDecompositionGraph


def test_task_decomposition_graph_supports_parallel_dimensions():
    dimensions = [
        "major items",
        "ratings",
        "relative distance",
        "opening windows",
        "route ordering",
        "meal options",
        "time allocation",
    ]
    graph = TaskDecompositionGraph().build("Create a one day plan", dimensions)
    assert len(graph["nodes"]) == 8
    assert len(graph["parallel_batches"][0]) == 7
    assert len(graph["parallel_batches"][1]) == 1
    synthesis = graph["nodes"][-1]
    assert synthesis["task_type"] == "synthesis"
    assert len(synthesis["depends_on"]) == 7


def test_parallel_retrieval_and_evidence_verification():
    tasks = TaskDecompositionGraph().build("request", ["alpha", "beta"])["nodes"][:2]

    async def retriever_a(task):
        return {
            "status": "success",
            "source_id": "source-a",
            "text": f"{task['parameters']['dimension']} value from source a",
            "facts": [{"value": task["parameters"]["dimension"], "confidence": 0.8}],
        }

    def retriever_b(task):
        return {
            "status": "success",
            "source_id": "source-b",
            "text": f"{task['parameters']['dimension']} value from source b",
            "facts": [{"value": task["parameters"]["dimension"], "confidence": 0.7}],
        }

    results = asyncio.run(ParallelRetrievalRuntime().run(tasks, [retriever_a, retriever_b]))
    assert len(results) == 2
    evidence_items = [source for result in results for source in result["material"]["sources"]]
    verification = EvidenceVerifier().verify(evidence_items, ["alpha", "beta"])
    assert verification["passed"] is True
    assert verification["source_count"] == 2
    assert verification["coverage_ratio"] == 1.0


def test_route_sequence_and_stable_synthesis():
    ranked = RouteOptimizer().optimize([
        {"id": "a", "quality": 0.9, "reliability": 0.9, "latency_ms": 800, "unit_cost": 0.1},
        {"id": "b", "quality": 0.6, "reliability": 0.5, "latency_ms": 4000, "unit_cost": 0.0},
    ])
    assert ranked[0]["id"] == "a"

    graph = TaskDecompositionGraph().build("request", ["alpha", "beta"])
    sequence = SequenceSynthesizer().synthesize(graph)
    assert sequence["count"] == 3

    answer = StableSynthesizer().synthesize(
        [{"task_id": "task_1", "material": {"sources": [{"summary": "Matched Parameter: useful result"}]}}],
        {"confidence": 0.8, "coverage_ratio": 1.0, "source_count": 2, "passed": True},
    )
    assert "Matched Parameter:" not in answer["answer"]
    assert answer["confidence"] == 0.8


def test_runtime_generated_schema_contracts_validate_graph_trace_and_facts():
    schemas = RuntimeSchemaGenerator()
    graph = TaskDecompositionGraph().build("request", ["alpha"])
    validate(instance=graph, schema=schemas.workflow_structure_schema())
    validate(instance={"run_id": "r1", "events": [{"type": "started", "timestamp": "t"}]}, schema=schemas.trace_structure_schema())
    validate(
        instance={"facts": [{"fact_id": "f1", "value": "v", "source_id": "s1"}], "relations": [], "confidence": 0.9},
        schema=schemas.fact_graph_schema(),
    )


def test_browser_mcp_and_self_healing_contracts():
    browser = PlaywrightBrowserRuntime()
    browser.attach_session(object())
    browser.record_network_event({"url": "https://example.test", "status": 200})
    evidence = browser.materialize_evidence("https://example.test", text="captured text", screenshot_path="shot.png")
    assert evidence["metadata"]["session_reused"] is True
    assert evidence["network_events"]
    assert evidence["screenshot_path"] == "shot.png"

    mcp = UniversalMCPRuntime()
    mcp.register_server("server", {"transport": "stdio"})
    planned = mcp.call_tool("server", "tool", {"x": 1})
    assert planned["status"] == "planned"

    repaired = SelfHealingRuntime().repair(
        {"code": "route_error"},
        [lambda ctx: {"status": "failed"}, lambda ctx: {"status": "repaired", "ctx": ctx}],
    )
    assert repaired["status"] == "repaired"
    assert repaired["failure_kind"] == "routing_failed"

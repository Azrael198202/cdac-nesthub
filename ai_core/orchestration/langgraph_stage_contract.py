from __future__ import annotations

from typing import Any, TypedDict

try:
    from langgraph.graph import StateGraph, END
except Exception:  # pragma: no cover
    StateGraph = None
    END = "__end__"


class RuntimeGraphState(TypedDict, total=False):
    run_id: str
    input: str
    results: dict[str, Any]
    node_index: int
    status: str
    pending_action: dict[str, Any]


STAGE_IO_CONTRACTS: tuple[dict[str, Any], ...] = (
    {"stage": "input_parsing", "input": ["raw_payload"], "output": ["input_record"], "must_not": ["execution_method", "tool_selection"]},
    {"stage": "intent_recognition", "input": ["input_record"], "output": ["intent_record"], "must_not": ["locked_plan", "runtime_execution"]},
    {"stage": "requirement_completion", "input": ["input_record", "intent_record"], "output": ["requirement_record"], "must_not": ["execution"]},
    {"stage": "context_awareness", "input": ["input_record", "intent_record", "requirement_record"], "output": ["context_record.clean_context"], "must_not": ["intent_reclassification"]},
    {"stage": "workflow_planning", "input": ["intent_record", "requirement_record", "context_record.clean_context"], "output": ["workflow", "agent_graph", "execution_decision", "planned_steps", "execution_plan"], "must": ["rank_fixed_execution_options", "lock_selected_action_type"]},
    {"stage": "execution_preparation", "input": ["execution_plan"], "output": ["resource_bundle"], "must": ["prepare_only_no_execution"]},
    {"stage": "pre_execution_validation", "input": ["execution_plan", "resource_bundle"], "output": ["validation_record"], "must": ["block_execution_until_passed"]},
    {"stage": "execution", "input": ["execution_plan", "resource_bundle", "validation_record"], "output": ["execution_record"], "must": ["follow_locked_action_only"]},
    {"stage": "result_verification", "input": ["execution_record"], "output": ["verification_record"]},
    {"stage": "feedback_repair", "input": ["validation_record", "verification_record"], "output": ["repair_record"]},
    {"stage": "final_synthesis", "input": ["execution_record", "verification_record"], "output": ["final_answer"]},
)


def build_stage_graph(node_functions: dict[str, Any] | None = None):
    """Build a LangGraph StateGraph from the fixed stage contract.

    The current runtime may still dispatch through its config-driven runner, but
    this graph contract is the canonical node order and IO policy for generated
    nodes. Pass async/sync functions keyed by stage name to compile an executable
    graph in integrations/tests.
    """
    if StateGraph is None:
        return None
    node_functions = node_functions or {}
    graph = StateGraph(RuntimeGraphState)

    async def passthrough(state: RuntimeGraphState) -> RuntimeGraphState:
        return state

    stages = [item["stage"] for item in STAGE_IO_CONTRACTS]
    for stage in stages:
        graph.add_node(stage, node_functions.get(stage) or passthrough)
    graph.set_entry_point(stages[0])
    for current, nxt in zip(stages, stages[1:]):
        graph.add_edge(current, nxt)
    graph.add_edge(stages[-1], END)
    return graph

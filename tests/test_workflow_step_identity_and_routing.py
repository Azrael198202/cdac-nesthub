from auxiliary_brain.studio.instruction_workflow_planner import InstructionWorkflowPlanner
from ai_core.graph.graph_visualization import GraphVisualStateBuilder


def test_unrelated_participant_route_becomes_generated_step():
    participants = [
        {"participant_id": "p_a", "agent_name": "Alpha Agent"},
        {"participant_id": "p_b", "agent_name": "Beta Agent"},
        {"participant_id": "p_c", "agent_name": "Other Agent", "parameter_contract": {"parameters": [{"name": "topic", "required": True, "values": []}] }},
    ]
    semantic_plan = {
        "steps": [
            {"id": "s1", "instruction_fragment": "Call the Alpha Agent.", "route": {"participant_id": "p_a"}, "depends_on": []},
            {"id": "s2", "instruction_fragment": "Call the Beta Agent.", "route": {"participant_id": "p_b"}, "depends_on": []},
            {"id": "s3", "instruction_fragment": "Combine the outputs from Alpha Agent and Beta Agent.", "route": {"participant_id": "p_c"}, "depends_on": ["s1", "s2"]},
        ]
    }
    counter = {"n": 0}
    def new_id(prefix):
        counter["n"] += 1
        return f"{prefix}_{counter['n']}"

    plan = InstructionWorkflowPlanner().plan(
        instruction="test",
        participants=participants,
        graph_id="g",
        new_id_fn=new_id,
        semantic_plan=semantic_plan,
    )
    assert plan.tasks[2]["step_type"] == "semantic_intermediate_step"
    assert plan.tasks[2]["participant_id"] != "p_c"
    assert "p_c" not in plan.selected_participants[0].get("participant_id", "")
    assert all(p.get("participant_id") != "p_c" for p in plan.selected_participants)
    assert plan.tasks[2]["graph_depends_on"] == ["g_delegate_1", "g_delegate_2"]
    assert plan.tasks[2]["depends_on"] == ["p_a", "p_b"]


def test_graph_uses_workflow_node_identity_not_participant_identity():
    graph = {
        "graph_id": "g",
        "tasks": [
            {"task_id": "node_1", "node_id": "node_1", "participant_id": "same_agent", "label": "First use"},
            {"task_id": "node_2", "node_id": "node_2", "participant_id": "same_agent", "label": "Second use", "graph_depends_on": ["node_1"]},
        ],
    }
    run = {"agent_results": [{"participant_id": "same_agent", "status": "completed"}]}
    state = GraphVisualStateBuilder().from_graph(graph, run)
    assert [n["id"] for n in state.nodes] == ["node_1", "node_2"]
    assert state.edges == [{"id": "edge_1", "from": "node_1", "to": "node_2", "label": "runtime_json", "status": "transferred"}]

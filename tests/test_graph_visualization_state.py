from ai_core.graph.graph_visualization import GraphVisualStateBuilder


def test_graph_visual_state_builds_lanes_and_edge_status_from_scheduler_summary():
    graph = {
        "graph_id": "g1",
        "nodes": [
            {"node_id": "a", "name": "A", "executor_type": "callable"},
            {"node_id": "b", "name": "B", "executor_type": "callable"},
            {"node_id": "c", "name": "C", "executor_type": "callable"},
        ],
        "edges": [{"from": "a", "to": "c"}, {"from": "b", "to": "c"}],
    }
    run = {"scheduler_summary": {"completed": ["a", "b"], "running": ["c"], "history": [{"event": "node_started", "node_id": "c"}]}}
    payload = GraphVisualStateBuilder().to_dict(GraphVisualStateBuilder().from_graph(graph, run))
    assert payload["graph_id"] == "g1"
    assert payload["status"] == "running"
    assert payload["lanes"] == [["a", "b"], ["c"]]
    assert {edge["status"] for edge in payload["edges"]} == {"transferred"}
    assert payload["summary"]["running_count"] == 1


def test_graph_visual_state_marks_repair_when_self_check_has_repair_plan():
    graph = {"graph_id": "g2", "nodes": [{"node_id": "a"}], "edges": []}
    run = {"self_check": {"repair_plan": [{"action": "rerun_unfinished_nodes", "reason": "node_not_completed"}]}}
    payload = GraphVisualStateBuilder().to_dict(GraphVisualStateBuilder().from_graph(graph, run))
    assert payload["status"] == "repair"
    assert payload["summary"]["repair_count"] == 1
    assert payload["events"][-1]["event"] == "repair_available"


def test_graph_visual_state_derives_edges_from_depends_on_without_domain_terms():
    graph = {
        "graph_id": "g3",
        "steps": [
            {"task_id": "first", "status": "completed"},
            {"task_id": "second", "depends_on": ["first"], "status": "pending"},
        ],
    }
    payload = GraphVisualStateBuilder().to_dict(GraphVisualStateBuilder().from_graph(graph, {}))
    assert payload["edges"] == [{"id": "edge_1", "from": "first", "to": "second", "label": "runtime_json", "status": "pending"}]
    assert payload["lanes"] == [["first"], ["second"]]

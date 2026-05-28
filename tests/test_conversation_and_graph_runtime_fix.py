from ai_core.graph.graph_visualization import GraphVisualStateBuilder


def test_graph_visualizer_matches_run_by_task_graph_id() -> None:
    builder = GraphVisualStateBuilder()
    snapshot = {
        "task_graphs": [
            {
                "graph_id": "graph_alpha",
                "task_name": "task_alpha",
                "tasks": [
                    {"participant_id": "node_a", "participant_name": "Alpha", "status": "pending"},
                    {"participant_id": "node_b", "participant_name": "Beta", "status": "pending", "depends_on": ["node_a"]},
                ],
            }
        ],
        "task_runs": [
            {
                "run_id": "run_alpha",
                "task_graph_id": "graph_alpha",
                "task_name": "task_alpha",
                "status": "running",
                "agent_results": [{"participant_id": "node_a", "status": "completed"}],
                "primary_runtime_events": [{"status": "running", "message": "Preparing participant: Beta"}],
            }
        ],
    }
    state = builder.from_snapshot(snapshot, graph_id="graph_alpha")
    statuses = {node["id"]: node["status"] for node in state.nodes}
    assert statuses["node_a"] == "completed"
    assert statuses["node_b"] == "running"
    assert state.summary["running_count"] == 1


def test_graph_visualizer_keeps_unmatched_graph_pending() -> None:
    builder = GraphVisualStateBuilder()
    snapshot = {
        "task_graphs": [{"graph_id": "graph_beta", "tasks": [{"participant_id": "node_a", "status": "pending"}]}],
        "task_runs": [{"task_graph_id": "other_graph", "agent_results": [{"participant_id": "node_a", "status": "completed"}]}],
    }
    state = builder.from_snapshot(snapshot, graph_id="graph_beta")
    assert state.nodes[0]["status"] == "pending"

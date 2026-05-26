from ai_core.graph.graph_visualization import GraphVisualStateBuilder


def test_explicit_graph_request_does_not_fallback_to_latest():
    b = GraphVisualStateBuilder()
    snapshot = {
        "task_graphs": [
            {"graph_id": "g_a", "task_name": "taskA", "tasks": [{"id": "a1", "label": "A"}]},
            {"graph_id": "g_b", "task_name": "taskB", "tasks": [{"id": "b1", "label": "B"}]},
        ],
        "task_runs": [],
        "participants": [],
    }
    state = b.from_snapshot(snapshot, graph_id="missing_task")
    assert state.graph_id == "missing_task"
    assert state.nodes == []
    assert {x["task_name"] for x in state.task_catalog} == {"taskA", "taskB"}


def test_task_catalog_and_participants_are_returned_without_cross_task_nodes():
    b = GraphVisualStateBuilder()
    snapshot = {
        "participants": [{"participant_id": "p1", "agent_name": "Agent One"}, {"participant_id": "p2", "agent_name": "Agent Two"}],
        "task_graphs": [
            {"graph_id": "g_a", "task_name": "taskA", "selected_participant_ids": ["p1"], "tasks": [{"participant_id": "p1", "label": "Agent One"}]},
            {"graph_id": "g_b", "task_name": "taskB", "selected_participant_ids": ["p2"], "tasks": [{"participant_id": "p2", "label": "Agent Two"}]},
        ],
        "task_runs": [{"task_name": "taskB", "status": "completed", "agent_results": [{"participant_id": "p2", "status": "completed"}]}],
    }
    state = b.from_snapshot(snapshot, graph_id="taskA")
    assert [n["id"] for n in state.nodes] == ["p1"]
    assert state.selected_task_name == "taskA"
    assert len(state.task_catalog) == 2
    assert len(state.participant_catalog) == 2

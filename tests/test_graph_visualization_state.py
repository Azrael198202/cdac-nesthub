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


def test_graph_visual_state_overlays_live_run_status_from_agent_results_and_progress_events():
    graph = {
        "graph_id": "g_live",
        "tasks": [
            {"participant_id": "p1", "source_instruction_fragment": "First", "status": "pending"},
            {"participant_id": "p2", "source_instruction_fragment": "Second", "status": "pending", "depends_on": ["p1"]},
        ],
    }
    run = {
        "task_name": "g_live",
        "status": "running",
        "agent_results": [{"participant_id": "p1", "status": "completed", "final_answer": "ok"}],
        "progress_events": [{"stage": "participant_2_primary_runtime", "status": "running", "label": "running"}],
    }
    payload = GraphVisualStateBuilder().to_dict(GraphVisualStateBuilder().from_graph(graph, run))
    status_by_id = {node["id"]: node["status"] for node in payload["nodes"]}
    assert status_by_id["p1"] == "completed"
    assert status_by_id["p2"] == "running"
    assert payload["status"] == "running"
    assert payload["summary"]["completed_count"] == 1
    assert payload["summary"]["running_count"] == 1
    assert payload["events"]


def test_graph_visual_state_marks_downstream_skipped_when_upstream_failed():
    graph = {
        "graph_id": "g_fail",
        "tasks": [
            {"participant_id": "p1", "source_instruction_fragment": "First", "status": "pending"},
            {"participant_id": "p2", "source_instruction_fragment": "Second", "status": "pending", "depends_on": ["p1"]},
        ],
    }
    run = {"task_name": "g_fail", "agent_results": [{"participant_id": "p1", "status": "failed"}]}
    payload = GraphVisualStateBuilder().to_dict(GraphVisualStateBuilder().from_graph(graph, run))
    status_by_id = {node["id"]: node["status"] for node in payload["nodes"]}
    assert status_by_id["p1"] == "failed"
    assert status_by_id["p2"] == "skipped"


def test_graph_visual_state_prefers_participant_label_for_noisy_task_fragment():
    snapshot = {
        "participants": [{"participant_id": "p1", "display_name": "Readable Node"}],
        "task_graphs": [{
            "graph_id": "g_label",
            "tasks": [{
                "participant_id": "p1",
                "step_type": "participant_execution",
                "source_instruction_fragment": "Step 1: Do one thing. Step 2: Do another thing. Step 3: Return the result.",
            }],
        }],
        "task_runs": [],
    }
    payload = GraphVisualStateBuilder().to_dict(GraphVisualStateBuilder().from_snapshot(snapshot, graph_id="g_label"))
    assert payload["nodes"][0]["label"] == "Readable Node"
    assert "Step 1" in payload["nodes"][0]["summary"]

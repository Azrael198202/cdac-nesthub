from ai_core.graph import EdgeDrivenScheduler, GraphBoundaryNormalizer, GraphSelfCheck


def test_graph_boundary_separates_non_executable_nodes_from_execution_graph():
    graph = {
        "nodes": [
            {"node_id": "n0", "node_type": "definition", "name": "descriptor"},
            {"node_id": "n1", "executable": True, "executor_type": "callable"},
            {"node_id": "n2", "executable": True, "executor_type": "callable"},
        ],
        "edges": [
            {"from": "n0", "to": "n1"},
            {"from": "n1", "to": "n2"},
        ],
    }
    partition = GraphBoundaryNormalizer().normalize(graph)
    assert [n["node_id"] for n in partition.execution_graph["nodes"]] == ["n1", "n2"]
    assert [n["node_id"] for n in partition.metadata_graph["nodes"]] == ["n0"]
    assert partition.dataflow_graph["edges"] == [{"from": "n1", "to": "n2", "data_contract": "runtime_json", "status": "pending"}]
    assert partition.boundary_report["metadata_node_count"] == 1


def test_edge_scheduler_unlocks_downstream_only_after_upstream_output_binding():
    partition = GraphBoundaryNormalizer().normalize({
        "nodes": [
            {"node_id": "a", "executable": True, "executor_type": "callable"},
            {"node_id": "b", "executable": True, "executor_type": "callable"},
            {"node_id": "c", "executable": True, "executor_type": "callable"},
        ],
        "edges": [{"from": "a", "to": "c"}, {"from": "b", "to": "c"}],
    })
    scheduler = EdgeDrivenScheduler()
    state = scheduler.create_state(partition.execution_graph, partition.dataflow_graph)
    assert [n["node_id"] for n in scheduler.ready_nodes(partition.execution_graph, partition.dataflow_graph, state)] == ["a", "b"]
    scheduler.mark_started("a", state)
    scheduler.bind_output("a", {"value": 1}, partition.dataflow_graph, state)
    assert [n["node_id"] for n in scheduler.ready_nodes(partition.execution_graph, partition.dataflow_graph, state)] == ["b"]
    scheduler.mark_started("b", state)
    scheduler.bind_output("b", {"value": 2}, partition.dataflow_graph, state)
    assert [n["node_id"] for n in scheduler.ready_nodes(partition.execution_graph, partition.dataflow_graph, state)] == ["c"]
    assert set(state.bound_inputs["c"].keys()) == {"a", "b"}


def test_graph_self_check_requires_edges_and_final_constraints_not_only_completed_status():
    partition = GraphBoundaryNormalizer().normalize({
        "nodes": [
            {"node_id": "a", "executable": True, "executor_type": "callable"},
            {"node_id": "b", "executable": True, "executor_type": "callable"},
        ],
        "edges": [{"from": "a", "to": "b"}],
    })
    scheduler = EdgeDrivenScheduler()
    state = scheduler.create_state(partition.execution_graph, partition.dataflow_graph)
    scheduler.mark_started("a", state)
    scheduler.bind_output("a", "x", partition.dataflow_graph, state)
    scheduler.mark_started("b", state)
    state.completed.add("b")
    state.running.discard("b")
    record = GraphSelfCheck().validate(
        original_request={"acceptance_constraints": {"non_empty_final": True, "min_chars": 5, "required_items": ["done"]}},
        partition=partition,
        scheduler_summary=scheduler.summary(state),
        final_output={"final_answer": "bad"},
    )
    assert record["status"] == "failed"
    assert {issue["code"] for issue in record["issues"]} >= {"final_output_too_short", "final_output_missing_required_items"}
    assert any(item["action"] == "rerun_final_synthesis" for item in record["repair_plan"])

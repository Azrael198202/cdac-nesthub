from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime
from auxiliary_brain.delegation.task_mind_graph import TaskMindGraphBuilder


def test_delegation_runtime_honors_selected_graph_nodes_without_text_refiltering():
    runtime = AgentDelegationRuntime()
    task_graph = {
        "instruction": "opaque instruction that names only the first capability",
        "selected_participant_ids": ["p1", "p2"],
    }
    participants = [
        {"participant_id": "p1", "name": "Declared first"},
        {"participant_id": "p2", "name": "Generated follow-up"},
    ]
    selected = runtime._select_participants(task_graph, participants)
    assert [p["participant_id"] for p in selected] == ["p1", "p2"]


def test_task_mind_graph_uses_explicit_dataflow_edges():
    task_graph = {
        "task_name": "graph",
        "tasks": [
            {"participant_id": "p1", "depends_on": []},
            {"participant_id": "p2", "depends_on": ["p1"]},
        ],
        "selected_participant_ids": ["p1", "p2"],
    }
    participants = [
        {"participant_id": "p1", "name": "First"},
        {"participant_id": "p2", "name": "Second"},
    ]
    graph = TaskMindGraphBuilder().build(task_graph, participants)
    assert graph["execution_plan"]["groups"] == [["p1"], ["p2"]]
    assert { (e["from"], e["to"]) for e in graph["edges"] } >= {("p1", "p2"), ("p2", "final_synthesis")}


def test_task_mind_graph_keeps_independent_nodes_parallel_when_no_edges():
    task_graph = {
        "task_name": "graph",
        "tasks": [
            {"participant_id": "p1", "depends_on": []},
            {"participant_id": "p2", "depends_on": []},
        ],
        "selected_participant_ids": ["p1", "p2"],
    }
    participants = [
        {"participant_id": "p1", "name": "First"},
        {"participant_id": "p2", "name": "Second"},
    ]
    graph = TaskMindGraphBuilder().build(task_graph, participants)
    assert graph["execution_plan"]["groups"] == [["p1", "p2"]]


def test_delegation_coordination_source_has_no_semantic_marker_tables():
    from pathlib import Path
    root = Path("auxiliary_brain/delegation")
    source = "\n".join(p.read_text() for p in root.glob("*.py"))
    forbidden = ["dependency" + "_markers", "result" + "-reference language"]
    assert all(token not in source for token in forbidden)

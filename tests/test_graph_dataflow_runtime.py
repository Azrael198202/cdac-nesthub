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


def test_final_synthesis_uses_terminal_graph_outputs_only():
    class Result:
        def __init__(self, participant_id):
            self.participant_id = participant_id
            self.participant_name = participant_id

    runtime = AgentDelegationRuntime()
    graph = {
        "edges": [
            {"from": "p1", "to": "p3"},
            {"from": "p2", "to": "p3"},
            {"from": "p3", "to": "final_synthesis"},
        ]
    }
    results = [Result("p1"), Result("p2"), Result("p3")]
    terminal = runtime._terminal_results_for_synthesis(results, graph)
    assert [item.participant_id for item in terminal] == ["p3"]


def test_final_synthesis_keeps_all_independent_outputs():
    class Result:
        def __init__(self, participant_id):
            self.participant_id = participant_id
            self.participant_name = participant_id

    runtime = AgentDelegationRuntime()
    graph = {"edges": [{"from": "p1", "to": "final_synthesis"}, {"from": "p2", "to": "final_synthesis"}]}
    results = [Result("p1"), Result("p2")]
    terminal = runtime._terminal_results_for_synthesis(results, graph)
    assert [item.participant_id for item in terminal] == ["p1", "p2"]


def test_single_terminal_projection_does_not_need_model():
    from ai_core.agent_delegation.primary_brain_client import PrimaryBrainDelegationClient

    client = PrimaryBrainDelegationClient()
    upstream = [{"name": "previous", "text": "Already prepared final text."}]
    assert client._project_single_upstream_result_if_possible("Return only the final result.", upstream) == "Already prepared final text."


def test_lean_step_prompt_excludes_full_graph_metadata():
    from ai_core.agent_delegation.primary_brain_client import PrimaryBrainDelegationClient

    client = PrimaryBrainDelegationClient()
    prompt = client._build_lean_step_prompt(
        "Apply the requested change.",
        [{"name": "source", "text": "abc"}],
    )
    assert "OBJECTIVE:" in prompt
    assert "INPUT:" in prompt
    assert "task_mind_graph" not in prompt
    assert "selected_participant_ids" not in prompt


def test_missing_parameter_fields_are_deduped_per_participant():
    runtime = AgentDelegationRuntime()
    participants = [{
        "participant_id": "p1",
        "name": "Generic Agent",
        "parameter_contract": {
            "parameters": [
                {"name": "value", "required": True, "values": []},
                {"name": "value", "required": True, "values": []},
            ]
        },
        "runtime_parameters": {},
    }]
    fields = runtime._collect_missing_agent_parameter_fields(participants)
    names = [f.get("name") for f in fields]
    assert sum(1 for name in names if str(name).endswith("value")) == 1

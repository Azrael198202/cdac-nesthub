from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime
from auxiliary_brain.studio.service import AgentStudioService
from ai_core.agent_delegation.primary_brain_client import PrimaryBrainDelegationClient
from ai_core.graph.graph_visualization import GraphVisualStateBuilder


def _participant(pid, name, artifacts=None, contract=None):
    return {
        "participant_id": pid,
        "name": name,
        "agent_name": name,
        "execution_objective": f"Run {name}",
        "uploaded_artifacts": artifacts or [],
        "parameter_contract": contract or {"contract_type": "agent_parameter_contract", "source": "runtime_llm", "parameters": [], "missing_information": []},
        "runtime_parameters": {},
    }


def test_task_level_resource_does_not_leak_to_all_participants():
    runtime = AgentDelegationRuntime()
    p1 = _participant("p1", "Alpha", artifacts=[{"artifact_id": "a1", "name": "method.py"}])
    p2 = _participant("p2", "Beta")
    task_graph = {"uploaded_artifacts": [{"artifact_id": "global", "name": "global.py"}], "tasks": []}

    assert runtime._participant_artifacts_for_task(p1, task_graph, [p1, p2])[0]["artifact_id"] == "a1"
    assert runtime._participant_artifacts_for_task(p2, task_graph, [p1, p2]) == []


def test_single_participant_can_use_task_level_resource():
    runtime = AgentDelegationRuntime()
    p1 = _participant("p1", "Alpha")
    task_graph = {"uploaded_artifacts": [{"artifact_id": "global", "name": "global.py"}], "tasks": []}
    assert runtime._participant_artifacts_for_task(p1, task_graph, [p1])[0]["artifact_id"] == "global"


def test_explicit_task_binding_is_node_scoped():
    runtime = AgentDelegationRuntime()
    p1 = _participant("p1", "Alpha")
    p2 = _participant("p2", "Beta")
    task_graph = {
        "tasks": [
            {"participant_id": "p1", "uploaded_artifacts": [{"artifact_id": "a1", "name": "method.py"}]},
        ]
    }
    assert runtime._participant_artifacts_for_task(p1, task_graph, [p1, p2])[0]["artifact_id"] == "a1"
    assert runtime._participant_artifacts_for_task(p2, task_graph, [p1, p2]) == []


def test_preflight_collects_only_bound_resource_inputs(monkeypatch):
    service = AgentStudioService()

    class DummyContract:
        def build_contract(self, *, state, step, step_id):
            return {
                "missing_parameter_fields": [{"field": "value", "required": True}],
                "status": "missing_parameters",
            }

    service.uploaded_artifact_contract = DummyContract()
    p1 = _participant("p1", "Alpha", artifacts=[{"artifact_id": "a1", "name": "method.py"}])
    p2 = _participant("p2", "Beta")
    task_graph = {"selected_participant_ids": ["p1", "p2"], "tasks": []}
    result = service._preflight_uploaded_artifact_parameters(task_graph, [p1, p2], {})
    fields = result["missing_inputs"]
    assert len(fields) == 1
    assert fields[0]["participant_id"] == "p1"


def test_planning_message_is_not_valid_result_material():
    client = PrimaryBrainDelegationClient()
    assert not client._answer_has_result_material("Agent actions and substeps planned with locked fixed execution options.")


def test_graph_labels_prefer_runtime_names_over_generic_step_labels():
    graph = {
        "graph_id": "g1",
        "tasks": [
            {"task_id": "t1", "participant_id": "p1", "label": "step_1", "step_type": "participant_execution"},
            {"task_id": "t2", "participant_id": "p2", "label": "step_2", "step_type": "participant_execution"},
        ],
    }
    snapshot = {
        "task_graphs": [graph],
        "participants": [
            {"participant_id": "p1", "agent_name": "Alpha"},
            {"participant_id": "p2", "agent_name": "Beta"},
        ],
        "task_runs": [],
    }
    state = GraphVisualStateBuilder().to_dict(GraphVisualStateBuilder().from_snapshot(snapshot, "g1"))
    labels = [node["label"] for node in state["nodes"]]
    assert labels == ["Alpha", "Beta"]

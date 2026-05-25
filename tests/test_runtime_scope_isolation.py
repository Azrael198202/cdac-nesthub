from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime
from auxiliary_brain.studio.service import AgentStudioService
from ai_core.agent_delegation.primary_brain_client import PrimaryBrainDelegationClient
from ai_core.graph.graph_visualization import GraphVisualStateBuilder


def test_task_level_artifacts_do_not_bind_to_every_node_when_ambiguous():
    runtime = AgentDelegationRuntime()
    graph = {
        "selected_participant_ids": ["p_a", "p_b"],
        "uploaded_artifacts": [{"artifact_id": "artifact_a", "name": "method.py"}],
        "tasks": [
            {"participant_id": "p_a", "label": "Agent A"},
            {"participant_id": "p_b", "label": "Agent B"},
        ],
    }
    assert runtime._node_uploaded_artifacts(graph, {"participant_id": "p_a"}) == []
    assert runtime._node_uploaded_artifacts(graph, {"participant_id": "p_b"}) == []


def test_node_bound_artifacts_are_visible_only_to_bound_node():
    runtime = AgentDelegationRuntime()
    artifact = {"artifact_id": "artifact_a", "name": "method.py"}
    graph = {
        "selected_participant_ids": ["p_a", "p_b"],
        "tasks": [
            {"participant_id": "p_a", "label": "Agent A", "uploaded_artifacts": [artifact]},
            {"participant_id": "p_b", "label": "Agent B"},
        ],
    }
    assert runtime._node_uploaded_artifacts(graph, {"participant_id": "p_a"}) == [artifact]
    assert runtime._node_uploaded_artifacts(graph, {"participant_id": "p_b"}) == []


def test_runtime_parameters_are_filtered_by_participant_contract():
    runtime = AgentDelegationRuntime()
    participant = {
        "participant_id": "p_a",
        "parameter_contract": {
            "parameters": [
                {"name": "alpha", "required": True, "values": []},
            ]
        },
    }
    graph = {"runtime_parameters": {"alpha": "1", "beta": "2"}}
    assert runtime._merged_runtime_parameters(graph, participant) == {"alpha": "1"}


def test_artifact_bound_node_can_see_task_runtime_values():
    runtime = AgentDelegationRuntime()
    participant = {"participant_id": "p_a"}
    graph = {
        "selected_participant_ids": ["p_a"],
        "uploaded_artifacts": [{"artifact_id": "artifact_a"}],
        "runtime_parameters": {"alpha": "1", "beta": "2"},
    }
    assert runtime._merged_runtime_parameters(graph, participant) == {"alpha": "1", "beta": "2"}


def test_metadata_fields_are_not_user_missing_inputs():
    runtime = AgentDelegationRuntime()
    participant = {
        "participant_id": "p_a",
        "parameter_contract": {
            "parameters": [
                {"name": "execution_objective", "required": True, "values": []},
                {"name": "real_input", "required": True, "values": []},
            ]
        },
    }
    fields = runtime._collect_missing_agent_parameter_fields([participant])
    names = {f.get("parameter_name") or f.get("name") or f.get("field") for f in fields}
    assert "execution_objective" not in names
    assert "real_input" in names


def test_artifact_preflight_does_not_scan_unbound_nodes(monkeypatch):
    service = AgentStudioService()
    calls = []

    def fake_build_contract(*, state, step, step_id):
        calls.append(step.get("uploaded_artifacts"))
        return {"missing_parameter_fields": [{"field": "alpha", "required": True}]}

    monkeypatch.setattr(service.uploaded_artifact_contract, "build_contract", fake_build_contract)
    artifact = {"artifact_id": "artifact_a", "name": "method.py"}
    graph = {
        "selected_participant_ids": ["p_a", "p_b"],
        "tasks": [
            {"participant_id": "p_a", "uploaded_artifacts": [artifact]},
            {"participant_id": "p_b"},
        ],
    }
    result = service._preflight_uploaded_artifact_parameters(
        graph,
        [{"participant_id": "p_a"}, {"participant_id": "p_b"}],
        {},
    )
    assert len(calls) == 1
    assert result["status"] == "requires_input"
    assert result["missing_inputs"][0]["participant_id"] == "p_a"


def test_planning_message_is_not_usable_result_material():
    client = PrimaryBrainDelegationClient()
    assert not client._answer_has_result_material("Agent actions and substeps planned with locked fixed execution options.")
    assert not client._answer_has_result_material("The workflow is blocked and did not execute a tool yet.")


def test_graph_node_label_prefers_participant_name():
    state = GraphVisualStateBuilder().from_graph(
        graph={
            "graph_id": "g1",
            "tasks": [{"participant_id": "p_a", "participant_name": "Clear Agent", "source_instruction_fragment": "long step"}],
        },
        run={},
    )
    assert state.nodes[0]["label"] == "Clear Agent"

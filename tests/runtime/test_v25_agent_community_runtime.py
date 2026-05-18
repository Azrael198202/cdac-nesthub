from pathlib import Path

from auxiliary_brain import AuxiliaryBrainRuntime
from auxiliary_brain.community.builder import RuntimeCommunityBuilder
from auxiliary_brain.community.community_runtime import RuntimeCommunityEngine


def test_v25_builds_and_persists_runtime_generated_community(tmp_path):
    spec = {
        "community_id": "generated_sample",
        "coordinator_agent_id": "agent_1",
        "agents": [
            {"agent_id": "agent_1", "role_label": "coordinator", "capability_labels": ["coordination"]},
            {"agent_id": "agent_2", "role_label": "collector", "capability_labels": ["collection"]},
        ],
        "activations": [
            {"activation_id": "activation_1", "mode": "cron", "expression": "0 6 * * *"}
        ],
        "tasks": [
            {"task_id": "task_1", "assigned_agent_id": "agent_2", "objective": "collect generated material", "output_ref": "material"},
            {"task_id": "task_2", "assigned_agent_id": "agent_1", "objective": "combine generated material", "input_refs": ["material"], "output_ref": "combined"},
        ],
        "edges": [{"from_task_id": "task_1", "to_task_id": "task_2"}],
    }
    runtime = AuxiliaryBrainRuntime(runtime_root=tmp_path / "runtime")
    result = runtime.create_from_specification(spec)
    assert result["status"] == "created"
    assert Path(result["paths"]["community"]).exists()
    assert Path(result["paths"]["tasks"]).exists()
    assert (tmp_path / "runtime" / "generated" / "agents" / "agent_1.json").exists()


def test_v25_dispatches_generated_task_graph_in_dependency_order():
    spec = {
        "community_id": "generated_dispatch",
        "coordinator_agent_id": "agent_1",
        "agents": [
            {"agent_id": "agent_1", "role_label": "coordinator"},
            {"agent_id": "agent_2", "role_label": "worker"},
        ],
        "tasks": [
            {"task_id": "task_2", "assigned_agent_id": "agent_1", "objective": "merge", "input_refs": ["first"], "output_ref": "second"},
            {"task_id": "task_1", "assigned_agent_id": "agent_2", "objective": "produce", "output_ref": "first"},
        ],
        "edges": [{"from_task_id": "task_1", "to_task_id": "task_2"}],
    }
    definition = RuntimeCommunityBuilder().build(spec)
    result = RuntimeCommunityEngine().dispatch(definition)
    assert result.status == "completed"
    assert result.executed_task_ids == ["task_1", "task_2"]
    assert "second" in result.outputs
    assert result.messages[-1]["receiver_id"] == "agent_1"


def test_v25_blocks_task_with_unknown_agent():
    spec = {
        "community_id": "generated_blocked",
        "coordinator_agent_id": "agent_1",
        "agents": [{"agent_id": "agent_1", "role_label": "coordinator"}],
        "tasks": [{"task_id": "task_1", "assigned_agent_id": "missing", "objective": "cannot run"}],
    }
    definition = RuntimeCommunityBuilder().build(spec)
    result = RuntimeCommunityEngine().dispatch(definition)
    assert result.status == "blocked"
    assert result.blocked_task_ids == ["task_1"]


def test_v25_core_files_do_not_contain_home_experience_terms():
    root = Path(__file__).resolve().parents[2] / "ai_core"
    forbidden = ["generated content", "item one", "item two", "runtime_assistant"]
    hits = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for term in forbidden:
            if term in text:
                hits.append((str(path.relative_to(root)), term))
    assert hits == []

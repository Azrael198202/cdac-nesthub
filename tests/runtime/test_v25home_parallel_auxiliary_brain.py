from pathlib import Path

from auxiliary_brain import AuxiliaryBrainRuntime


def test_v25home_auxiliary_brain_is_parallel_to_ai_core():
    project_root = Path(__file__).resolve().parents[2]
    assert (project_root / "ai_core").is_dir()
    assert (project_root / "auxiliary_brain").is_dir()
    assert not (project_root / "ai_core" / "runtime" / "community").exists()
    assert not (project_root / "ai_core" / "extensions" / "auxiliary_brain.py").exists()


def test_v25home_auxiliary_trace_origin_is_explicit(tmp_path):
    spec = {
        "community_id": "generated_parallel_sample",
        "coordinator_agent_id": "agent_1",
        "agents": [{"agent_id": "agent_1", "role_label": "coordinator"}],
        "tasks": [{"task_id": "task_1", "assigned_agent_id": "agent_1", "objective": "produce", "output_ref": "out"}],
    }
    runtime = AuxiliaryBrainRuntime(runtime_root=tmp_path / "runtime")
    result = runtime.run_specification(spec)
    assert result["origin"] == "auxiliary_brain"
    assert result["trace"]["origin"] == "auxiliary_brain"
    assert Path(result["trace"]["trace_path"]).exists()


def test_v25home_runtime_generated_content_is_shared(tmp_path):
    spec = {
        "community_id": "generated_shared_runtime",
        "coordinator_agent_id": "agent_1",
        "agents": [{"agent_id": "agent_1", "role_label": "coordinator"}],
        "tasks": [{"task_id": "task_1", "assigned_agent_id": "agent_1", "objective": "produce", "output_ref": "out"}],
    }
    result = AuxiliaryBrainRuntime(runtime_root=tmp_path / "runtime").create_from_specification(spec)
    assert Path(result["paths"]["community"]).parts[-3:] == ("generated", "communities", "generated_shared_runtime.json")
    assert Path(result["paths"]["tasks"]).parts[-3:] == ("generated", "tasks", "generated_shared_runtime.json")
    assert (tmp_path / "runtime" / "generated" / "agents" / "agent_1.json").exists()

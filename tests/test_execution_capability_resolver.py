from pathlib import Path

from ai_core.context.execution_capability import ExecutionCapabilityResolver
from ai_core.context.execution_reuse_store import ExecutionReuseStore


def test_capability_resolver_prefers_verified_executable_over_saved_model_mode(tmp_path: Path):
    script = tmp_path / "asset.py"
    script.write_text("def run(value):\n    return value\n", encoding="utf-8")
    asset = {
        "execution_mode": "llm_generation",
        "artifact_paths": [str(script)],
        "parameter_schema": [{"field": "value", "required": True}],
    }
    capability = ExecutionCapabilityResolver().resolve(asset, {"value": "ok"})
    assert capability.mode == "executable_artifact"
    assert capability.requires_model is False
    assert capability.callable_name == "run"


def test_capability_resolver_uses_model_only_when_no_executable_artifact():
    asset = {"execution_mode": "llm_generation", "artifact_paths": []}
    capability = ExecutionCapabilityResolver().resolve(asset, {})
    assert capability.mode == "model_generation"
    assert capability.requires_model is True


def test_repair_candidate_is_recorded_generically(tmp_path: Path):
    store = ExecutionReuseStore(root=tmp_path)
    record = store.record_repair_candidate(
        task_name="task_alpha",
        feedback="The reused result did not match the expected execution evidence.",
        run_payload={"run_id": "run_1"},
    )
    loaded = store.latest_repair_candidate("task_alpha")
    assert record["repair_id"].startswith("repair_")
    assert loaded is not None
    assert loaded["run_id"] == "run_1"

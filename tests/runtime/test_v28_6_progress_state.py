from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime
from auxiliary_brain.storage.json_store import JsonStore


def test_progress_events_are_recorded(tmp_path):
    store = JsonStore(root=tmp_path / "runtime")
    runtime = AgentDelegationRuntime(store=store, primary_client=None)
    payload = {"run_id": "delegation_run_test", "progress_events": []}
    runtime._record_progress(payload, "stage_a", "Stage A", "running")
    saved = store.read_json("generated/results/delegation_run_test.json")
    assert saved["current_stage"] == "stage_a"
    assert saved["progress_events"][-1]["label"] == "Stage A"

from __future__ import annotations

import asyncio
from pathlib import Path

from ai_core.context.execution_reuse_store import ExecutionReuseStore
from auxiliary_brain.studio.service import AgentStudioService


def test_execution_reuse_registers_and_runs_python_artifact(tmp_path):
    script = tmp_path / "unit_script.py"
    script.write_text("print('reuse-ok')\n", encoding="utf-8")
    store = ExecutionReuseStore(root=tmp_path)
    task_graph = {"task_name": "task_unit", "graph_id": "graph_unit"}
    participants = [{"participant_id": "p1", "display_name": "Agent", "parameter_contract": {"parameters": []}}]
    run_payload = {
        "run_id": "run_unit",
        "status": "completed",
        "synthesis": {"final_answer": f"generated at {script}"},
        "agent_results": [{"workflow_results": {"generated_file": str(script)}}],
    }
    registered = store.register_success(task_graph=task_graph, participants=participants, run_payload=run_payload)
    assert registered["ok"] is True
    decision = store.decide("task_unit", {})
    assert decision.reusable is True
    assert decision.asset and decision.asset["execution_mode"] == "python_artifact"
    result = asyncio.run(store.execute_reused_asset(asset=decision.asset, provided_inputs={}))
    assert result["status"] == "completed"
    assert result["context_trace"]["planning_used"] is False
    assert "reuse-ok" in result["final_answer"]


def test_execution_reuse_requires_saved_parameters(tmp_path):
    store = ExecutionReuseStore(root=tmp_path)
    task_graph = {"task_name": "task_params", "parameter_contract": {"parameters": [{"field": "value", "required": True}]}}
    participants = []
    run_payload = {"run_id": "run_params", "status": "completed", "synthesis": {"final_answer": "ok"}}
    store.register_success(task_graph=task_graph, participants=participants, run_payload=run_payload)
    decision = store.decide("task_params", {})
    assert decision.reusable is False
    assert decision.reason == "missing_runtime_inputs"
    assert decision.missing_inputs and decision.missing_inputs[0]["field"] == "value"
    assert store.decide("task_params", {"value": "x"}).reusable is True


def test_short_answer_cache_does_not_require_llm(tmp_path):
    store = ExecutionReuseStore(root=tmp_path)
    store.save_short_answer(query="Can you speak testlanguage?", answer="Yes.")
    hit = store.get_short_answer("can you speak testlanguage")
    assert hit and hit["answer"] == "Yes."


def test_studio_direct_ephemeral_answer_is_not_promoted_to_long_memory():
    service = AgentStudioService()
    answer = service._direct_ephemeral_answer("can you speak esperanto?")
    assert answer == "Yes, I can respond in esperanto."


def test_python_artifact_wins_over_write_instruction_profile(tmp_path):
    script = tmp_path / "artifact_script.py"
    script.write_text("print('artifact-wins')\n", encoding="utf-8")
    store = ExecutionReuseStore(root=tmp_path)
    registered = store.register_success(
        task_graph={"task_name": "task_artifact"},
        participants=[{"display_name": "Artifact Agent", "instruction": "Write a Python script that produces a result", "parameter_contract": {"parameters": [{"field": "unused", "required": True}]}}],
        run_payload={"run_id": "r1", "status": "completed", "synthesis": {"final_answer": str(script)}},
    )
    assert registered["ok"] is True
    asset = registered["asset"]
    assert asset["execution_mode"] == "python_artifact"
    assert asset["parameter_schema"] == []
    result = asyncio.run(store.execute_reused_asset(asset=asset, provided_inputs={}))
    assert result["status"] == "completed"
    assert result["context_trace"]["artifact_registry"] is True
    assert result["context_trace"]["llm_used"] is False
    assert "artifact-wins" in result["final_answer"]


def test_python_function_artifact_extracts_parameters_and_invokes_function(tmp_path):
    script = tmp_path / "method_file.py"
    script.write_text(
        "def run_item(city_name: list, date_str: list):\n"
        "    return {'city_name': city_name, 'date_str': date_str}\n",
        encoding="utf-8",
    )
    store = ExecutionReuseStore(root=tmp_path)
    registered = store.register_success(
        task_graph={"task_name": "task_method"},
        participants=[{"display_name": "Method Agent"}],
        run_payload={"run_id": "r2", "status": "completed", "artifact_path": str(script)},
    )
    asset = registered["asset"]
    assert asset["execution_mode"] == "python_artifact"
    assert [x["field"] for x in asset["parameter_schema"]] == ["city_name", "date_str"]
    missing = store.decide("task_method", {})
    assert missing.reason == "missing_runtime_inputs"
    decision = store.decide("task_method", {"city_name": ["Fukuoka"], "date_str": ["2026-05-24"]})
    assert decision.reusable is True
    result = asyncio.run(store.execute_reused_asset(asset=decision.asset, provided_inputs={"city_name": ["Fukuoka"], "date_str": ["2026-05-24"]}))
    assert result["status"] == "completed"
    assert result["invoked_function"] == "run_item"
    assert "Fukuoka" in result["final_answer"]


def test_reused_long_running_artifact_output_is_bounded_and_compacted(tmp_path, monkeypatch):
    script = tmp_path / "loop_script.py"
    script.write_text(
        "import time\n"
        "print('first-result')\n"
        "while True:\n"
        "    print('repeat-result')\n"
        "    time.sleep(0.01)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RUNTIME_REUSE_TIMEOUT_SECONDS", "1")
    store = ExecutionReuseStore(root=tmp_path)
    registered = store.register_success(
        task_graph={"task_name": "task_loop"},
        participants=[{"display_name": "Reusable Agent"}],
        run_payload={"run_id": "r_loop", "status": "completed", "artifact_path": str(script)},
    )
    result = asyncio.run(store.execute_reused_asset(asset=registered["asset"], provided_inputs={}))
    assert result["status"] == "completed"
    assert result["timed_out"] in {False, True}
    assert "first-result" in result["final_answer"]
    assert result["final_answer"].count("repeat-result") == 1
    assert result["context_trace"]["planning_used"] is False
    assert result["context_trace"]["llm_used"] is False


def test_output_compaction_removes_near_duplicate_runtime_lines(tmp_path):
    store = ExecutionReuseStore(root=tmp_path)
    text = "2026-01-01 10:00:00 - Sunday\n2026-01-01 10:00:00 - Sunday - Reminder: current value is 10:00:00\n"
    compact = store.compact_final_answer(text)
    assert compact.count("2026-01-01") == 1
    assert "Reminder" in compact


def test_reuse_initial_collection_includes_optional_schema_fields(tmp_path):
    script = tmp_path / "method_optional.py"
    script.write_text(
        "def run_item(required_value: list, optional_value: list = None):\n"
        "    return {'required_value': required_value, 'optional_value': optional_value}\n",
        encoding="utf-8",
    )
    store = ExecutionReuseStore(root=tmp_path)
    registered = store.register_success(
        task_graph={"task_name": "task_optional"},
        participants=[{"display_name": "Agent"}],
        run_payload={"run_id": "r_optional", "status": "completed", "artifact_path": str(script)},
    )
    asset = registered["asset"]
    assert [(f["field"], f["required"]) for f in asset["parameter_schema"]] == [("required_value", True), ("optional_value", False)]
    first_decision = store.decide("task_optional", {})
    assert first_decision.reason == "missing_runtime_inputs"
    assert [(f["field"], f["required"]) for f in (first_decision.missing_inputs or [])] == [("required_value", True), ("optional_value", False)]
    resumed_decision = store.decide("task_optional", {"required_value": ["x"]})
    assert resumed_decision.reusable is True


def test_single_line_duplicate_phrase_is_compacted_generically(tmp_path):
    store = ExecutionReuseStore(root=tmp_path)
    compact = store.compact_final_answer("network request failed network request failed")
    assert compact == "network request failed"


def test_reuse_initial_collection_includes_optional_when_unrelated_runtime_state_exists(tmp_path):
    script = tmp_path / "method_optional_unrelated.py"
    script.write_text(
        "def run_item(required_value: list, optional_value: list = None):\n"
        "    return {'required_value': required_value, 'optional_value': optional_value}\n",
        encoding="utf-8",
    )
    store = ExecutionReuseStore(root=tmp_path)
    store.register_success(
        task_graph={"task_name": "task_optional_unrelated"},
        participants=[{"display_name": "Agent"}],
        run_payload={"run_id": "r_optional_unrelated", "status": "completed", "artifact_path": str(script)},
    )
    first_decision = store.decide("task_optional_unrelated", {"runtime_metadata": "present"})
    assert first_decision.reason == "missing_runtime_inputs"
    assert [(f["field"], f["required"]) for f in (first_decision.missing_inputs or [])] == [("required_value", True), ("optional_value", False)]
    resumed_decision = store.decide("task_optional_unrelated", {"runtime_metadata": "present", "required_value": ["x"]})
    assert resumed_decision.reusable is True

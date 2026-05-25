import asyncio

from auxiliary_brain.studio.service import AgentStudioService
from auxiliary_brain.storage.json_store import JsonStore
from ai_core.context.execution_reuse_store import ExecutionReuseStore


def test_bare_task_name_routes_to_execution_without_chat(tmp_path, monkeypatch):
    store = JsonStore(tmp_path / "runtime")
    service = AgentStudioService(store=store)
    store.write_json("generated/tasks/taskC.json", {
        "graph_id": "taskC",
        "task_name": "taskC",
        "selected_participant_ids": [],
        "status": "created",
    })
    script = tmp_path / "time_agent.py"
    script.write_text("print('direct-task-output')\n", encoding="utf-8")
    reuse = ExecutionReuseStore(root=tmp_path / "reuse")
    monkeypatch.setattr(service, "execution_reuse_store", reuse)
    reuse.register_success(
        task_graph={"task_name": "taskC"},
        participants=[],
        run_payload={
            "status": "completed",
            "run_id": "run_1",
            "synthesis": {"final_answer": "ok"},
            "artifact_path": str(script),
        },
    )

    result = asyncio.run(service.handle_message("taskC"))

    assert result["status"] == "completed"
    assert result["task_name"] == "taskC"
    assert "direct-task-output" in result["final_answer"]
    assert result["context_trace"]["planning_used"] is False
    assert result["context_trace"]["llm_used"] is False


def test_conversation_direct_answer_accepts_context_argument(monkeypatch, tmp_path):
    from ai_core.interaction.conversation_core_runtime import ConversationCoreRuntime

    runtime = ConversationCoreRuntime()

    async def fake_stage(run_id, node_id, prompt, user_payload, schema, *, fallback):
        if node_id == "conversation_execution_response":
            assert "session_context" in user_payload
            return {"answer": "ok"}
        return dict(fallback)

    monkeypatch.setattr(runtime, "_json_stage", fake_stage)
    answer = asyncio.run(runtime._direct_answer("hello", {}, {}, {"session_context": {}}, {}, "run"))
    assert answer == "ok"

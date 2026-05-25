from ai_core.context.session_memory_store import SessionMemoryStore
from ai_core.context.vector_memory_store import VectorMemoryStore


def test_session_store_persists_turns_and_boundary(tmp_path):
    store = SessionMemoryStore(root=tmp_path / "sessions")
    sid = store.start_or_get_session()
    store.append_turn(
        session_id=sid,
        run_id="run_1",
        user_input="first input",
        final_answer="first answer",
        stage_results={"stage": {"status": "completed"}},
    )
    store.save_summary(session_id=sid, summary_text="first input first answer", open_items=[], source_run_id="run_1")
    window = store.load_context_window(sid)
    assert window.session_id == sid
    assert window.recent_turns[-1]["final_answer"] == "first answer"
    assert "first answer" in window.rolling_summary
    assert store.boundary_status(sid)["turn_count"] == 1


def test_vector_memory_local_retrieval(tmp_path):
    store = VectorMemoryStore(root=tmp_path / "vectors")
    store.add_text(text="alpha beta gamma", metadata={"k": "v"}, usage_scope="retrieval_context")
    hits = store.search("alpha beta", usage_scope="retrieval_context")
    assert hits
    assert hits[0]["score"] > 0

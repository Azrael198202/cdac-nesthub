from pathlib import Path

from ai_core.context.session_memory_store import SessionMemoryStore


def test_session_store_recreates_missing_parent_directory(tmp_path: Path) -> None:
    root = tmp_path / "runtime" / "sessions"
    store = SessionMemoryStore(root=root)
    assert (root / "session_memory.sqlite3").exists()

    # Simulate runtime cleanup after process startup. The store must recover
    # before the next sqlite connection instead of crashing with OperationalError.
    (root / "session_memory.sqlite3").unlink()
    root.rmdir()

    sid = store.start_or_get_session("session_test")
    snapshot = store.get_session_snapshot(sid)

    assert snapshot["session_id"] == "session_test"
    assert (root / "session_memory.sqlite3").exists()


from ai_core.interaction.conversation_core_runtime import ConversationCoreRuntime
from auxiliary_brain.runtime.observability.model_prompt_registry import ModelPromptRegistry


def test_retrieved_context_keeps_active_session_only():
    runtime = ConversationCoreRuntime()
    hits = [
        {"text": "same session", "metadata": {"session_id": "s1"}, "score": 0.9},
        {"text": "other session", "metadata": {"session_id": "s2"}, "score": 0.99},
        {"text": "missing session", "metadata": {}, "score": 0.8},
    ]

    kept = runtime._filter_retrieved_context_for_session(hits, session_id="s1", limit=5)

    assert [x["text"] for x in kept] == ["same session"]


def test_prompt_event_id_is_stable_without_polling_index():
    registry = ModelPromptRegistry()
    event = {
        "run_id": "job_abc",
        "node_id": "node_x",
        "workflow": "flow",
        "graph": "graph",
        "model": "model",
        "provider": "provider",
    }

    first = registry._stable_event_id(event)
    second = registry._stable_event_id(dict(event))

    assert first == second
    assert "job_abc" in first
    assert not first.endswith(":0")

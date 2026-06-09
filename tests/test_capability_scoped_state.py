from ai_core.runtime.state.capability_scope import CapabilityScopedStateStore


def test_capability_scoped_interactions_do_not_cross_contaminate(tmp_path):
    store = CapabilityScopedStateStore(tmp_path)
    time_req = store.record_interaction(
        session_id="session_a",
        run_id="run_time",
        capability_id="current_time_provider",
        interaction_type="runtime_tool_live_verification",
        request={"kind": "runtime_tool_live_verification", "fields": [{"field": "timezone"}, {"field": "format"}]},
    )
    mail_req = store.record_interaction(
        session_id="session_a",
        run_id="run_mail",
        capability_id="gmail_sender",
        interaction_type="runtime_tool_live_verification",
        request={"kind": "runtime_tool_live_verification", "fields": [{"field": "to"}, {"field": "subject"}]},
    )
    assert time_req["request"]["scope"]["capability_id"] == "current_time_provider"
    assert mail_req["request"]["scope"]["capability_id"] == "gmail_sender"
    assert store.active_for_scope(session_id="session_a", run_id="run_mail", capability_id="gmail_sender")["request"]["fields"][0]["field"] == "to"
    assert store.active_for_scope(session_id="session_a", run_id="run_mail", capability_id="current_time_provider") is None
    assert store.is_request_current(time_req["request"], session_id="session_a", run_id="run_time") is True
    assert store.is_request_current(time_req["request"], session_id="session_a", run_id="run_mail") is False

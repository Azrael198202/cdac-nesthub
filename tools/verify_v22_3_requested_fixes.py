from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def test_agent_studio_send_event_chain_and_progress_history() -> None:
    html = read("apps/web/agent_studio.html")
    assert "async function sendMessage()" in html
    assert "fetch('/api/agent-studio/message'" in html
    assert "submitting request to runtime" in html
    assert "startLocalExecutionHistory" in html
    assert "Runtime execution history" in html
    assert "Local request history" in html
    assert "await refreshSessions()" in html
    assert "window.lastStudioState" in html

def test_settings_presentation_profile() -> None:
    settings = read("apps/web/settings.html")
    assert "settingsPresentationProfile" in settings
    assert "User" in settings and "Advanced" in settings and "Developer" in settings and "Diagnostic" in settings
    assert "presentation_profile" in settings
    store = read("ai_core/runtime/modeling/user_model_selection.py")
    assert "presentation_profile" in store
    assert "_normalize_presentation_profile" in store

def test_no_direct_runtime_observation_shortcut() -> None:
    client = read("ai_core/agent_delegation/primary_brain_client.py")
    assert "Direct observation shortcuts are disabled" in client
    assert "current_markers" not in client
    assert "temporal_markers" not in client
    assert "self_contained_runtime_observation" not in client
    assert "_try_self_contained_runtime_observation" not in client
    start = client.find("async def execute_agent_request")
    end = client.find("message = self._build_agent_message", start)
    assert start >= 0 and end > start
    assert "disabled_direct_observation_shortcut" not in client[start:end]

if __name__ == "__main__":
    test_agent_studio_send_event_chain_and_progress_history()
    test_settings_presentation_profile()
    test_no_direct_runtime_observation_shortcut()
    print("verification passed")

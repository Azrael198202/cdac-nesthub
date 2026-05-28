from pathlib import Path

from ai_core.media.video_generation_setup_wizard import VideoGenerationSetupWizard
from ai_core.config.paths import RUNTIME_CONFIGS


def test_video_setup_wizard_creates_workflow_fields():
    wizard = VideoGenerationSetupWizard()
    req = wizard.interaction_request(
        setup_actions=[{"provider": "local_video_generation", "kind": "prepare_local_video_runtime", "reason": "workflow_template_source_missing"}],
        attempted=[{"provider": "local_video_generation", "reason": "workflow_template_source_missing"}],
    )
    assert req
    assert req["kind"] == "video_generation_setup_wizard"
    names = {f["field"] for f in req["fields"]}
    assert "video_workflow_source" in names


def test_video_setup_wizard_persists_runtime_config(tmp_path, monkeypatch):
    # Uses the project's runtime config path by design; the wizard should be able
    # to write persistent runtime configuration without requiring shell exports.
    wizard = VideoGenerationSetupWizard()
    payload = wizard.apply_inputs({
        "video_workflow_source": "https://example.com/workflow.json",
        "VIDEO_GENERATION_ENDPOINT": "https://api.example.com/video",
    })
    assert payload["ok"] is True
    path = RUNTIME_CONFIGS / "media" / "video_generation.yaml"
    text = path.read_text(encoding="utf-8")
    assert "https://example.com/workflow.json" in text
    assert "https://api.example.com/video" in text

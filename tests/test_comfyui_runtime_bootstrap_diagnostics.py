from __future__ import annotations

import json
from pathlib import Path

from ai_core.media.image_generation_service import ImageGenerationService


def test_incomplete_comfyui_root_is_repaired_and_cloned(tmp_path, monkeypatch):
    service = ImageGenerationService()
    root = tmp_path / "comfyui"
    root.mkdir()
    (root / "README.md").write_text("partial", encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("print('ok')", encoding="utf-8")
    (source / "requirements.txt").write_text("", encoding="utf-8")

    monkeypatch.setattr("shutil.which", lambda name: "git" if name == "git" else None)

    def fake_run(cmd, text=True, capture_output=True, timeout=0):
        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""
        if "clone" in cmd:
            target = Path(cmd[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "main.py").write_text("print('ready')", encoding="utf-8")
            (target / "requirements.txt").write_text("", encoding="utf-8")
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    result = service._install_runtime(root=root, install={"create_venv": False, "install_requirements": False, "allow_external_runtime_cleanup": True})
    assert result["ok"] is True
    assert (root / "main.py").exists()
    assert list(tmp_path.glob("comfyui.incomplete.*"))


def test_comfyui_clone_failure_returns_log_path(tmp_path, monkeypatch):
    service = ImageGenerationService()
    root = tmp_path / "comfyui"
    monkeypatch.setattr("shutil.which", lambda name: "git" if name == "git" else None)

    def fake_run(cmd, text=True, capture_output=True, timeout=0):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "network failed"
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    result = service._install_runtime(root=root, install={})
    assert result["ok"] is False
    assert result["reason"] == "runtime_clone_failed"
    assert result.get("log_path")


def test_comfyui_integrity_detects_missing_main(tmp_path):
    service = ImageGenerationService()
    root = tmp_path / "comfyui"
    root.mkdir()
    (root / "requirements.txt").write_text("", encoding="utf-8")
    result = service._comfyui_runtime_integrity(root)
    assert result["ok"] is False
    assert "main.py" in result["missing_files"]

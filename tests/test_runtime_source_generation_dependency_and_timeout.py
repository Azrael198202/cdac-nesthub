from __future__ import annotations

import subprocess
from pathlib import Path

from ai_core.executors import tool_call_executor as executor_module
from ai_core.executors.tool_call_executor import ToolCallExecutor


def test_generated_artifact_timeout_with_output_is_success(tmp_path: Path, monkeypatch):
    artifact = tmp_path / "generated.py"
    artifact.write_text("print('first result', flush=True)\nwhile True:\n    pass\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args", args[0] if args else "python"), timeout=30, output=b"first result\n", stderr=b"")

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)
    executor = ToolCallExecutor()
    result = executor._execute_python_artifact(artifact)
    assert result["returncode"] == 0
    assert result["timed_out"] is True
    assert result["bounded_by_runtime"] is True
    assert "first result" in result["stdout"]


def test_runtime_source_generation_prompt_requires_bounded_execution():
    source = Path("ai_core/executors/tool_call_executor.py").read_text(encoding="utf-8")
    assert "must finish by itself" in source
    assert "Do not create unbounded loops" in source
    assert "For repeated output, emit a small bounded sample and exit" in source

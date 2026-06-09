from pathlib import Path
import json

from auxiliary_brain.capability_acquisition.acquisition_router import RuntimeCapabilityGapImplementer


def test_effectful_generated_source_without_dry_run_guard_is_rejected(tmp_path):
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / "manifest.json").write_text(json.dumps({
        "runtime_execution_policy": {"side_effects": "runtime_declared"}
    }), encoding="utf-8")
    (tool_dir / "tool.py").write_text(
        "import smtplib\n"
        "def run(payload):\n"
        "    with smtplib.SMTP_SSL('example.invalid', 465) as server:\n"
        "        return {'status': 'success'}\n",
        encoding="utf-8",
    )
    result = RuntimeCapabilityGapImplementer()._effectful_runtime_test_mode_guard(tool_dir=tool_dir)
    assert result["passed"] is False
    assert result["status"] == "missing_runtime_test_mode_guard"


def test_effectful_generated_source_with_explicit_dry_run_guard_is_accepted(tmp_path):
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / "manifest.json").write_text(json.dumps({
        "runtime_execution_policy": {"side_effects": "runtime_declared"}
    }), encoding="utf-8")
    (tool_dir / "tool.py").write_text(
        "import smtplib\n"
        "def run(payload):\n"
        "    runtime = payload.get('_runtime', {}) if isinstance(payload, dict) else {}\n"
        "    dry_run = bool(runtime.get('dry_run'))\n"
        "    if dry_run:\n"
        "        return {'status': 'success', 'data': {'dry_run': True}}\n"
        "    with smtplib.SMTP_SSL('example.invalid', 465) as server:\n"
        "        return {'status': 'success'}\n",
        encoding="utf-8",
    )
    result = RuntimeCapabilityGapImplementer()._effectful_runtime_test_mode_guard(tool_dir=tool_dir)
    assert result["passed"] is True


def test_local_runtime_persistence_is_allowed_without_early_dry_run(tmp_path):
    tool_dir = tmp_path / "timer_tool"
    tool_dir.mkdir()
    (tool_dir / "manifest.json").write_text(json.dumps({
        "runtime_execution_policy": {"side_effects": "none"}
    }), encoding="utf-8")
    (tool_dir / "tool.py").write_text(
        "import os, json\n"
        "def run(payload=None):\n"
        "    os.makedirs('runtime_data', exist_ok=True)\n"
        "    with open('runtime_data/timers.json', 'w', encoding='utf-8') as f:\n"
        "        json.dump({'items': []}, f)\n"
        "    return {'status': 'completed', 'data': {'persisted': True}}\n",
        encoding="utf-8",
    )
    result = RuntimeCapabilityGapImplementer()._effectful_runtime_test_mode_guard(tool_dir=tool_dir)
    assert result["passed"] is True
    assert result["status"] == "local_state_sandbox_allowed"


def test_external_policy_with_local_write_still_requires_early_test_mode(tmp_path):
    tool_dir = tmp_path / "external_local_write_tool"
    tool_dir.mkdir()
    (tool_dir / "manifest.json").write_text(json.dumps({
        "runtime_execution_policy": {"side_effects": "external_write"}
    }), encoding="utf-8")
    (tool_dir / "tool.py").write_text(
        "def run(payload=None):\n"
        "    with open('out.txt', 'w') as f:\n"
        "        f.write('x')\n"
        "    return {'status': 'completed'}\n",
        encoding="utf-8",
    )
    result = RuntimeCapabilityGapImplementer()._effectful_runtime_test_mode_guard(tool_dir=tool_dir)
    assert result["passed"] is False
    assert result["status"] == "missing_runtime_test_mode_guard"

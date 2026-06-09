from pathlib import Path
import json

from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator
from auxiliary_brain.capability_acquisition.acquisition_router import RuntimeCapabilityGapImplementer


def test_llm_artifact_cannot_remove_declared_connection_or_secret_schema():
    gen = RuntimeBlueprintArtifactGenerator(llm_client=None)
    declared_connection = {
        "type": "object",
        "required": ["connection_value"],
        "properties": {"connection_value": {"type": "string", "title": "Connection Value"}},
    }
    declared_secret = {
        "type": "object",
        "required": ["secret_value"],
        "properties": {"secret_value": {"type": "string", "title": "Secret Value"}},
    }
    generated_connection = {"type": "object", "properties": {}, "required": []}
    generated_secret = {"type": "object", "properties": {}, "required": []}

    merged_connection = gen._merge_declared_schema(declared_connection, generated_connection, default_name="connection")
    merged_secret = gen._merge_declared_schema(declared_secret, generated_secret, default_name="secrets")

    assert "connection_value" in merged_connection["properties"]
    assert "secret_value" in merged_secret["properties"]
    assert "connection_value" in merged_connection["required"]
    assert "secret_value" in merged_secret["required"]


def test_effectful_guard_is_policy_driven_and_requires_early_test_branch(tmp_path: Path):
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / "manifest.json").write_text(json.dumps({"runtime_execution_policy": {"side_effects": "external"}}), encoding="utf-8")
    (tool_dir / "tool.py").write_text(
        "def run(payload=None):\n"
        "    client = object()\n"
        "    client.send('x')\n"
        "    return {'status':'completed'}\n",
        encoding="utf-8",
    )
    router = RuntimeCapabilityGapImplementer()
    result = router._effectful_runtime_test_mode_guard(tool_dir=tool_dir)
    assert not result["passed"]
    assert result["status"] == "missing_runtime_test_mode_guard"

    (tool_dir / "tool.py").write_text(
        "def run(payload=None):\n"
        "    runtime = (payload or {}).get('_runtime', {})\n"
        "    dry_run = bool(runtime.get('dry_run'))\n"
        "    if dry_run:\n"
        "        return {'status':'completed', 'data': {'dry_run': True}}\n"
        "    client = object()\n"
        "    client.send('x')\n"
        "    return {'status':'completed'}\n",
        encoding="utf-8",
    )
    result = router._effectful_runtime_test_mode_guard(tool_dir=tool_dir)
    assert result["passed"]


def test_effectful_guard_open_mode_literal_helper_does_not_crash(tmp_path: Path):
    tool_dir = tmp_path / "tool_open"
    tool_dir.mkdir()
    (tool_dir / "manifest.json").write_text(json.dumps({"runtime_execution_policy": {"side_effects": "external"}}), encoding="utf-8")
    (tool_dir / "tool.py").write_text(
        "def run(payload=None):\n"
        "    with open('x.txt', 'w') as f:\n"
        "        f.write('x')\n"
        "    return {'status':'completed'}\n",
        encoding="utf-8",
    )
    router = RuntimeCapabilityGapImplementer()
    result = router._effectful_runtime_test_mode_guard(tool_dir=tool_dir)
    assert not result["passed"]
    assert result["status"] == "missing_runtime_test_mode_guard"

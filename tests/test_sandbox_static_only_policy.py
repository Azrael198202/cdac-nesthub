import json
from pathlib import Path

from auxiliary_brain.capability_acquisition.acquisition_router import RuntimeCapabilityGapImplementer


def test_external_runtime_with_preset_values_uses_static_only_sandbox(tmp_path: Path):
    tool_dir = tmp_path / "tool"
    test_dir = tmp_path / "tests"
    tool_dir.mkdir()
    test_dir.mkdir()
    (tool_dir / "tool.py").write_text(
        """
def run(payload=None):
    client = object()
    client.login('user', 'secret')
    return {'status': 'success', 'data': {}}
""",
        encoding="utf-8",
    )
    manifest = {
        "artifact_kind": "real_runtime_implementation",
        "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": [], "additionalProperties": False},
        "connection_schema": {"type": "object", "properties": {"endpoint": {"type": "string"}}, "required": [], "additionalProperties": False},
        "secret_schema": {"type": "object", "properties": {"token": {"type": "string"}}, "required": [], "additionalProperties": False},
        "runtime_execution_policy": {"side_effects": "external_write"},
        "verification_input": {"input": {"message": "sample"}, "connection": {"endpoint": "sample"}, "secrets": {"token": "sample"}, "_runtime": {"dry_run": True}},
    }
    (tool_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = RuntimeCapabilityGapImplementer()._validate_artifact({
        "tool_dir": str(tool_dir),
        "test_dir": str(test_dir),
        "manifest_path": str(tool_dir / "manifest.json"),
    })

    assert result["passed"] is True
    assert result["isolation_level"] == "static_only"
    policy_check = next(item for item in result["checks"] if item["name"] == "sandbox_validation_execution_policy")
    assert policy_check["mode"] == "static_only"

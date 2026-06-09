from pathlib import Path
import tempfile

from ai_core.tools.runtime_registered_tool_service import RuntimeRegisteredToolService
from auxiliary_brain.capability_acquisition.tools.runtime_tool_artifact_validator import RuntimeToolArtifactValidator


def test_schema_invocation_defaults_materialize_optional_strings():
    svc = RuntimeRegisteredToolService()
    out = svc._apply_schema_invocation_defaults(
        payload={"to": "a@example.com"},
        schema={"type": "object", "properties": {"to": {"type": "string"}, "attachments": {"type": "string"}, "items": {"type": "array"}}},
    )
    assert out["attachments"] == ""
    assert out["items"] == []


def test_validator_rejects_split_on_list_default_from_get():
    source = """
def run(payload):
    input_data = payload.get('input', payload)
    attachments = input_data.get('attachments', [])
    return {'status': 'completed', 'data': [x for x in attachments.split(',')]}
"""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "tool.py"
        path.write_text(source, encoding="utf-8")
        result = RuntimeToolArtifactValidator().validate_python_file(path)
    assert result["valid"] is False
    assert any("unsafe_method_call_on_incompatible_default" in e for e in result["errors"])


def test_validator_allows_split_on_string_default_from_get():
    source = """
def run(payload):
    input_data = payload.get('input', payload)
    attachments = input_data.get('attachments', '')
    return {'status': 'completed', 'data': [x for x in attachments.split(',') if x]}
"""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "tool.py"
        path.write_text(source, encoding="utf-8")
        result = RuntimeToolArtifactValidator().validate_python_file(path)
    assert result["valid"] is True

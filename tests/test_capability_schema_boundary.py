from auxiliary_brain.capability_acquisition.schema_boundary import CapabilitySchemaBoundary
from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator
from auxiliary_brain.runtime.capability.registered_tool_parameter_bridge import RegisteredToolParameterBridge


def test_schema_boundary_splits_lifecycle_by_annotations_without_domain_terms():
    boundary = CapabilitySchemaBoundary()
    result = boundary.normalize(
        input_schema={
            "type": "object",
            "properties": {
                "runtime_value": {"type": "string"},
                "profile_value": {"type": "string", "x-runtime-source": "connection"},
                "protected_value": {"type": "string", "writeOnly": True},
            },
            "required": ["runtime_value", "profile_value", "protected_value"],
        },
        connection_schema={},
        secret_schema={},
        verification_input={
            "input": {"runtime_value": "r", "profile_value": "c", "protected_value": "s"}
        },
    )

    assert set(result["input_schema"]["properties"]) == {"runtime_value"}
    assert set(result["connection_schema"]["properties"]) == {"profile_value"}
    assert set(result["secret_schema"]["properties"]) == {"protected_value"}
    assert result["input_schema"]["required"] == ["runtime_value"]
    assert result["connection_schema"]["required"] == ["profile_value"]
    assert result["secret_schema"]["required"] == ["protected_value"]
    assert result["verification_input"] == {
        "input": {"runtime_value": "r"},
        "connection": {"profile_value": "c"},
        "secrets": {"protected_value": "s"},
    }


def test_bridge_only_collects_runtime_input_schema_not_preset_sections():
    bridge = RegisteredToolParameterBridge()
    participant = {
        "participant_id": "p1",
        "participant_name": "Worker",
        "runtime_parameters": {
            "runtime_value": "from task",
            "profile_value": "must not be forwarded",
            "protected_value": "must not be forwarded",
        },
        "capability_profile": {
            "tool_summary": {
                "input_schema": {
                    "type": "object",
                    "properties": {"runtime_value": {"type": "string"}},
                    "required": ["runtime_value"],
                },
                "connection_schema": {
                    "type": "object",
                    "properties": {"profile_value": {"type": "string"}},
                    "required": ["profile_value"],
                },
                "secret_schema": {
                    "type": "object",
                    "properties": {"protected_value": {"type": "string"}},
                    "required": ["protected_value"],
                },
            }
        },
    }

    result = bridge.build_invocation(participant=participant, provided_values=participant["runtime_parameters"])
    assert result["missing"] == []
    assert result["input_data"] == {"runtime_value": "from task"}


def test_contract_guard_rejects_reading_preset_fields_from_input():
    generator = RuntimeBlueprintArtifactGenerator()
    artifact = {
        "files": [
            {
                "path": "tool.py",
                "content": """
def run(payload):
    data = payload.get('input', {})
    leaked = data.get('profile_value')
    return {'status': 'success', 'value': leaked}
""",
            }
        ]
    }
    violations = generator._generated_artifact_contract_violations(
        artifact,
        input_schema={"type": "object", "properties": {"runtime_value": {"type": "string"}}, "required": []},
        connection_schema={"type": "object", "properties": {"profile_value": {"type": "string"}}, "required": ["profile_value"]},
        secret_schema={"type": "object", "properties": {}, "required": []},
    )
    assert any("profile_value" in item and "payload['input']" in item for item in violations)
